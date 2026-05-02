"""Loom daemon — wires all components into a running process.

Owns the bootstrap sequence, adaptor lifecycle, signal handling,
graceful shutdown, and the DaemonContext singleton used by the WebUI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import sys
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from loom.adaptor.arxiv import ArxivAdaptor, ArxivSourceConfig
from loom.adaptor.base import BaseAdaptor
from loom.adaptor.github import GitHubAdaptor, GitHubSourceConfig
from loom.adaptor.rss import RSSAdaptor, RSSSourceConfig
from loom.config import LoomConfig, check_pid_file, ensure_loom_dirs, load_config
from loom.core.eventbus import EventBus
from loom.core.mailbox import Mailbox
from loom.observability.metrics import MetricsCollector
from loom.orchestrator.dispatcher import Dispatcher
from loom.orchestrator.policy import PolicyEngine
from loom.orchestrator.session import SessionManager
from loom.state.store import Store

logger = logging.getLogger(__name__)

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def setup_logging(log_path: Path, foreground: bool = False) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)

    loom_logger = logging.getLogger("loom")
    loom_logger.setLevel(logging.DEBUG)

    # File handler — always active
    fh = RotatingFileHandler(log_path, maxBytes=10 * 1024 * 1024, backupCount=3)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(LOG_FORMAT))
    loom_logger.addHandler(fh)

    # Console handler — only in foreground mode
    if foreground:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter(LOG_FORMAT))
        loom_logger.addHandler(ch)


def _write_pid(pid_path: Path) -> None:
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))


def _remove_pid(pid_path: Path) -> None:
    try:
        pid_path.unlink(missing_ok=True)
    except OSError:
        pass


def _resolve_proxy(config: LoomConfig) -> str | None:
    if config.daemon.proxy:
        return config.daemon.proxy
    return (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )


# ---------------------------------------------------------------------------
# DaemonContext — shared runtime state
# ---------------------------------------------------------------------------


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
    _mailbox_enabled: bool = field(default=True, repr=False)

    @property
    def mailbox_enabled(self) -> bool:
        return self._mailbox_enabled

    async def set_mailbox_enabled(self, enabled: bool) -> None:
        """Start or stop all adaptors (mailbox collection)."""
        if enabled and not self._mailbox_enabled:
            for ad in self.adaptors:
                try:
                    await ad.start()
                    logger.info("Started %s adaptor", ad.name)
                except Exception:
                    logger.exception("Failed to start %s adaptor", ad.name)
            self._mailbox_enabled = True
            logger.info("Mailbox enabled — adaptors running")
        elif not enabled and self._mailbox_enabled:
            for ad in self.adaptors:
                try:
                    await ad.stop()
                except Exception:
                    logger.exception("Error stopping %s adaptor", ad.name)
            self._mailbox_enabled = False
            logger.info("Mailbox disabled — adaptors stopped")


def get_context() -> DaemonContext:
    from loom.api_server import app

    ctx = getattr(app.state, "ctx", None)
    if ctx is None:
        raise RuntimeError("Daemon not running")
    return ctx


def set_context(ctx: DaemonContext) -> None:
    from loom.api_server import app

    app.state.ctx = ctx


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
        token = os.environ.get("GITHUB_TOKEN")
        proxy = _resolve_proxy(config)
        gh = GitHubAdaptor(token=token, proxy=proxy)
        for src in github_sources:
            gh.add_source(
                GitHubSourceConfig(
                    owner=src["owner"],
                    repo=src["repo"],
                    poll_interval=src.get("poll_interval", 120),
                    state=src.get("state", "all"),
                    events=src.get("events", ["issues", "pull_requests"]),
                    labels_filter=src.get("labels_filter"),
                    group=src.get("group", ""),
                )
            )
        gh.set_callback(mailbox.receive)
        adaptors.append(gh)

    # One Gmail adaptor
    gmail_sources = [s for s in sources if s.get("kind") == "gmail"]
    if gmail_sources:
        from loom.adaptor.gmail import GmailAdaptor

        proxy = _resolve_proxy(config)
        for src in gmail_sources:
            secrets = Path(
                src.get("client_secrets", "~/.loom/credentials/gmail-client-secrets.json")
            ).expanduser()
            gmail = GmailAdaptor(
                client_secrets_path=secrets,
                token_path=Path(src["token_path"]).expanduser() if "token_path" in src else None,
                query=src.get("query", "is:unread -in:chats newer_than:1d"),
                poll_seconds=src.get("poll_seconds", 30),
                proxy_url=proxy,
                group=src.get("group", ""),
            )
            gmail.set_callback(mailbox.receive)
            adaptors.append(gmail)

    # One RSS adaptor handles multiple feeds
    rss_sources = [s for s in sources if s.get("kind") == "rss"]
    if rss_sources:
        proxy = _resolve_proxy(config)
        rss = RSSAdaptor(proxy=proxy)
        for src in rss_sources:
            rss.add_source(
                RSSSourceConfig(
                    url=src["url"],
                    poll_interval=src.get("poll_interval", 300),
                    title_filter=src.get("title_filter", []),
                    group=src.get("group", ""),
                )
            )
        rss.set_callback(mailbox.receive)
        adaptors.append(rss)

    # One arxiv adaptor handles multiple queries
    arxiv_sources = [s for s in sources if s.get("kind") == "arxiv"]
    if arxiv_sources:
        arx = ArxivAdaptor(proxy=_resolve_proxy(config))
        for src in arxiv_sources:
            arx.add_source(
                ArxivSourceConfig(
                    query=src.get("query", ""),
                    categories=src.get("categories", []),
                    keywords=src.get("keywords", []),
                    poll_interval=src.get("poll_interval", 3600),
                    max_results=src.get("max_results", 50),
                    group=src.get("group", ""),
                )
            )
        arx.set_callback(mailbox.receive)
        adaptors.append(arx)

    # Stub adaptors
    for src in sources:
        kind = src.get("kind", "")
        if kind not in ("github", "gmail", "rss", "arxiv"):
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

    pid_path = config.paths.data_dir / "loom.pid"

    # --- Pre-flight checks ---
    existing_pid = check_pid_file(pid_path)
    if existing_pid is not None:
        logger.error("Daemon already running (PID %d)", existing_pid)
        raise SystemExit(1)

    # Check port availability
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        test_sock.settimeout(1)
        test_sock.bind((config.daemon.host, config.daemon.port))
        test_sock.close()
    except OSError as exc:
        logger.error(
            "Port %d on %s is already in use: %s",
            config.daemon.port,
            config.daemon.host,
            exc,
        )
        raise SystemExit(1)

    # --- Core infrastructure ---
    bus = EventBus()
    store = Store(db_path=config.paths.data_dir / "loom.db")
    await store.init()
    mailbox = Mailbox(store, bus)
    metrics = MetricsCollector()

    # --- Orchestrator ---
    bundled_prompt_dir = Path(__file__).parent / "prompts"
    bundled_policy_dir = Path(__file__).parent / "policies"

    session_mgr = SessionManager(
        max_concurrent=config.agent.max_concurrent,
        prompt_dir=config.paths.prompts_dir,
        bundled_prompt_dir=bundled_prompt_dir,
    )
    policy_engine = PolicyEngine(
        policy_dir=config.paths.policies_dir,
        bundled_dir=bundled_policy_dir,
    )
    dispatcher = Dispatcher(
        bus, session_mgr, policy_engine, mailbox, agent_enabled=True, config=config
    )

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

    # --- Set context (stored on FastAPI app.state) ---
    from loom.api_server import app

    set_context(ctx)

    # --- Start components ---
    await dispatcher.start()
    metrics.set_online(True)

    # Drain pending envelopes from previous runs (respects semaphore)
    if dispatcher.agent_enabled:
        dispatcher._start_drain()

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
    import loom.webui.app  # noqa: F401 — side-effect: mounts built frontend if dist/ present

    uv_config = uvicorn.Config(
        app,
        host=config.daemon.host,
        port=config.daemon.port,
        log_level="info",
    )
    server = uvicorn.Server(uv_config)
    uvicorn_task = asyncio.create_task(server.serve())
    _write_pid(pid_path)

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
    _remove_pid(pid_path)
    logger.info("Loom daemon shut down")


if __name__ == "__main__":
    import os
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
                if (val.startswith('"') and val.endswith('"')) or (
                    val.startswith("'") and val.endswith("'")
                ):
                    val = val[1:-1]
                os.environ.setdefault(key, val)

    config = load_config()
    foreground = "--foreground" in sys.argv
    setup_logging(config.paths.data_dir / "loom.log", foreground=foreground)

    try:
        asyncio.run(run_daemon(config))
    except SystemExit as exc:
        if exc.code not in (0, None):
            logger.error("Daemon exited with code %s", exc.code)
        raise
    except KeyboardInterrupt:
        logger.info("Interrupted")
    except Exception:
        logger.exception("Daemon crashed with unexpected error")
        raise SystemExit(1)
