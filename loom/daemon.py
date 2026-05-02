"""Loom daemon — wires all components into a running process.

Owns the bootstrap sequence, adaptor lifecycle, signal handling,
graceful shutdown, and the DaemonContext singleton used by the WebUI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from dataclasses import dataclass, field
from pathlib import Path

import uvicorn

from loom.adaptor.base import BaseAdaptor
from loom.adaptor.github import GitHubAdaptor, GitHubSourceConfig
from loom.config import LoomConfig, ensure_loom_dirs, load_config
from loom.core.eventbus import EventBus
from loom.core.mailbox import Mailbox
from loom.observability.metrics import MetricsCollector
from loom.orchestrator.dispatcher import Dispatcher
from loom.orchestrator.policy import PolicyEngine
from loom.orchestrator.session import SessionManager
from loom.state.store import Store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DaemonContext — shared runtime state
# ---------------------------------------------------------------------------

_ctx: DaemonContext | None = None


@dataclass
class DaemonContext:
    config: LoomConfig
    store: Store
    bus: EventBus
    mailbox: Mailbox
    metrics: MetricsCollector
    session_mgr: SessionManager
    policy_engine: PolicyEngine
    dispatcher: Dispatcher
    adaptors: list[BaseAdaptor] = field(default_factory=list)


def get_context() -> DaemonContext:
    if _ctx is None:
        raise RuntimeError("Daemon not running")
    return _ctx


def set_context(ctx: DaemonContext) -> None:
    global _ctx
    _ctx = ctx


# ---------------------------------------------------------------------------
# Adaptor factory
# ---------------------------------------------------------------------------


def _build_adaptors(
    sources: list[dict],
    mailbox: Mailbox,
    config: LoomConfig,
) -> list[BaseAdaptor]:
    """Create adaptor instances from config source entries."""
    adaptors: list[BaseAdaptor] = []

    # Group github sources — one adaptor handles multiple repos
    github_sources = [s for s in sources if s.get("kind") == "github"]
    if github_sources:
        import os

        token = os.environ.get("GITHUB_TOKEN")
        gh = GitHubAdaptor(token=token)
        for src in github_sources:
            gh.add_source(
                GitHubSourceConfig(
                    owner=src["owner"],
                    repo=src["repo"],
                    poll_interval=src.get("poll_interval", 120),
                    state=src.get("state", "all"),
                    events=src.get("events", ["issues", "pull_requests"]),
                    labels_filter=src.get("labels_filter"),
                )
            )
        gh.set_callback(mailbox.receive)
        adaptors.append(gh)

    # One Gmail adaptor
    gmail_sources = [s for s in sources if s.get("kind") == "gmail"]
    if gmail_sources:
        from loom.adaptor.gmail import GmailAdaptor

        for src in gmail_sources:
            secrets = Path(
                src.get("client_secrets", "~/.loom/credentials/gmail-client-secrets.json")
            ).expanduser()
            gmail = GmailAdaptor(
                mailbox=mailbox,
                client_secrets_path=secrets,
                token_path=Path(src["token_path"]).expanduser() if "token_path" in src else None,
                state_path=Path(src["state_path"]).expanduser() if "state_path" in src else None,
                query=src.get("query", "is:unread -in:chats newer_than:1d"),
                poll_seconds=src.get("poll_seconds", 30),
            )
            adaptors.append(gmail)

    # Stub adaptors
    for src in sources:
        kind = src.get("kind", "")
        if kind not in ("github", "gmail"):
            logger.warning("Adaptor kind '%s' is not yet implemented, skipping", kind)

    return adaptors


# ---------------------------------------------------------------------------
# Cursor persistence
# ---------------------------------------------------------------------------


async def _restore_github_cursors(adaptor: GitHubAdaptor, store: Store) -> None:
    raw = await store.get_adaptor_state("github", "cursors")
    if raw:
        cursors = json.loads(raw)
        adaptor.restore_cursors(cursors)
        logger.info("Restored %d GitHub cursors", len(cursors))


async def _save_github_cursors(adaptor: GitHubAdaptor, store: Store) -> None:
    cursors = adaptor.get_cursors()
    if cursors:
        await store.save_adaptor_state("github", "cursors", json.dumps(cursors))
        logger.info("Saved %d GitHub cursors", len(cursors))


# ---------------------------------------------------------------------------
# Main daemon entry point
# ---------------------------------------------------------------------------


async def run_daemon(config: LoomConfig | None = None) -> None:
    """Bootstrap and run the Loom daemon until shutdown."""
    if config is None:
        config = load_config()

    ensure_loom_dirs(config)

    # --- Core infrastructure ---
    bus = EventBus()
    store = Store(db_path=config.paths.data_dir / "loom.db")
    await store.init()
    mailbox = Mailbox(store, bus)
    metrics = MetricsCollector()

    # --- Orchestrator ---
    session_mgr = SessionManager(
        max_concurrent=config.agent.max_concurrent,
        prompt_dir=config.paths.prompts_dir,
    )
    policy_engine = PolicyEngine(policy_dir=config.paths.policies_dir)
    dispatcher = Dispatcher(bus, session_mgr, policy_engine, mailbox)

    # Wire session completion callback
    session_mgr._on_complete = dispatcher.handle_session_complete

    # --- Adaptors ---
    adaptors = _build_adaptors(config.sources, mailbox, config)

    # Restore GitHub cursors before starting
    for ad in adaptors:
        if isinstance(ad, GitHubAdaptor):
            await _restore_github_cursors(ad, store)

    # --- Set context (for WebUI access) ---
    ctx = DaemonContext(
        config=config,
        store=store,
        bus=bus,
        mailbox=mailbox,
        metrics=metrics,
        session_mgr=session_mgr,
        policy_engine=policy_engine,
        dispatcher=dispatcher,
        adaptors=adaptors,
    )
    set_context(ctx)

    # --- Start components ---
    await dispatcher.start()
    metrics.set_online(True)

    started_adaptors: list[BaseAdaptor] = []
    for ad in adaptors:
        try:
            await ad.start()
            started_adaptors.append(ad)
            logger.info("Started %s adaptor", ad.name)
        except Exception:
            logger.exception("Failed to start %s adaptor, skipping", ad.name)

    ctx.adaptors = started_adaptors

    # --- Uvicorn (API server) ---
    from loom.webui.app import app

    uv_config = uvicorn.Config(
        app,
        host=config.daemon.host,
        port=config.daemon.port,
        log_level="info",
    )
    server = uvicorn.Server(uv_config)
    uvicorn_task = asyncio.create_task(server.serve())

    logger.info("Loom daemon online at http://%s:%d", config.daemon.host, config.daemon.port)

    # --- Signal handling + shutdown ---
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_shutdown() -> None:
        if not shutdown_event.is_set():
            logger.info("Shutdown signal received")
            shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _request_shutdown)

    await shutdown_event.wait()

    # --- Graceful teardown ---
    logger.info("Beginning graceful shutdown...")
    metrics.set_online(False)

    for ad in started_adaptors:
        try:
            await ad.stop()
        except Exception:
            logger.exception("Error stopping %s adaptor", ad.name)

    # Save cursors
    for ad in started_adaptors:
        if isinstance(ad, GitHubAdaptor):
            try:
                await _save_github_cursors(ad, store)
            except Exception:
                logger.exception("Error saving GitHub cursors")

    await dispatcher.stop()

    server.should_exit = True
    try:
        await asyncio.wait_for(uvicorn_task, timeout=5.0)
    except TimeoutError:
        logger.warning("Uvicorn did not shut down in time")

    await store.close()
    logger.info("Loom daemon shut down")


if __name__ == "__main__":
    import asyncio
    import os

    # Load .env files before anything else
    from pathlib import Path

    from loom.config import DEFAULT_LOOM_DIR, load_config

    for p in (Path(".env"), DEFAULT_LOOM_DIR / ".env"):
        if p.is_file():
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                os.environ.setdefault(key, val)

    asyncio.run(run_daemon(load_config()))
