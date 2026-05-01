"""Loom CLI commands."""

from __future__ import annotations

import asyncio
import os
import sys
import webbrowser
from collections import Counter
from pathlib import Path

import click

from loom.cli.view.render import doctor_report, envelope_detail, envelope_table, status_bar
from loom.cli.view.theme import make_console
from loom.config import DEFAULT_LOOM_DIR, LoomConfig, load_config
from loom.core.envelope import Envelope, EnvelopeStatus
from loom.core.eventbus import EventBus
from loom.core.mailbox import Mailbox
from loom.state.store import Store

# ---------------------------------------------------------------------------
# inbox / show
# ---------------------------------------------------------------------------


@click.command("inbox")
@click.option("--source", help="Filter by source (github, gmail, rss, anet)")
@click.option(
    "--status",
    type=click.Choice([str(s) for s in EnvelopeStatus]),
    help="Filter by status",
)
@click.option("--limit", default=50, type=int, show_default=True)
def inbox(source: str | None, status: str | None, limit: int) -> None:
    """List envelopes — newest first."""
    status_enum = EnvelopeStatus(status) if status else None
    envelopes = asyncio.run(_query(source=source, status=status_enum, limit=limit))
    make_console().print(envelope_table(envelopes))


@click.command("show")
@click.argument("envelope_id")
def show(envelope_id: str) -> None:
    """Show a single envelope by id (or 8-char prefix)."""
    envelope = asyncio.run(_lookup(envelope_id))
    if envelope is None:
        click.echo(f"Error: no envelope matching '{envelope_id}'")
        raise SystemExit(1)
    make_console().print(envelope_detail(envelope))


# ---------------------------------------------------------------------------
# approve / reject — set envelope status; daemon executes the action
# ---------------------------------------------------------------------------


@click.command("approve")
@click.argument("envelope_id")
def approve(envelope_id: str) -> None:
    """Approve the proposed action on an envelope."""
    envelope = asyncio.run(_lookup(envelope_id))
    if envelope is None:
        click.echo(f"Error: no envelope matching '{envelope_id}'")
        raise SystemExit(1)
    asyncio.run(_set_status(envelope.id, EnvelopeStatus.DONE))
    click.echo(f"  Approved: {envelope.id[:8]}")


@click.command("reject")
@click.argument("envelope_id")
@click.option("--reason", default="", help="Optional reason recorded with the rejection")
def reject(envelope_id: str, reason: str) -> None:
    """Reject the proposed action; the envelope is marked dismissed."""
    envelope = asyncio.run(_lookup(envelope_id))
    if envelope is None:
        click.echo(f"Error: no envelope matching '{envelope_id}'")
        raise SystemExit(1)
    asyncio.run(_set_status(envelope.id, EnvelopeStatus.DISMISSED))
    suffix = f" ({reason})" if reason else ""
    click.echo(f"  Rejected: {envelope.id[:8]}{suffix}")


# ---------------------------------------------------------------------------
# daemon (single command — fills captain's TODO)
# ---------------------------------------------------------------------------


@click.command("daemon")
def daemon() -> None:
    """Start the Loom daemon (mailbox + dispatcher + web UI)."""
    click.echo("Starting Loom daemon...")
    os.execvp(sys.executable, [sys.executable, "-m", "loom.daemon"])


# ---------------------------------------------------------------------------
# status — envelope count by status, read from Store
# ---------------------------------------------------------------------------


@click.command("status")
def status() -> None:
    """Show queue backlog and envelope status counts."""
    counts = asyncio.run(_status_counts())
    info: dict = {
        "online": False,
        "active_sessions": 0,
        "queue_backlog": counts.get(str(EnvelopeStatus.PENDING), 0)
        + counts.get(str(EnvelopeStatus.PROCESSING), 0),
    }
    console = make_console()
    console.print(status_bar(info))
    if counts:
        for s, n in sorted(counts.items()):
            console.print(f"  {s:<20} {n}", style="loom.muted")


# ---------------------------------------------------------------------------
# doctor / ui
# ---------------------------------------------------------------------------


@click.command("doctor")
def doctor() -> None:
    """Diagnose the local Loom setup."""
    config = load_config()
    checks: list[tuple[str, bool, str]] = []
    checks.extend(_check_loom_dir(config))
    checks.extend(_check_config())
    checks.extend(_check_sources(config))
    checks.extend(_check_database(config))

    make_console().print(doctor_report(checks))
    if any(not ok for _, ok, _ in checks):
        raise SystemExit(1)


@click.command("ui")
def ui() -> None:
    """Open the Loom web UI in a browser."""
    cfg = load_config()
    url = f"http://{cfg.daemon.host}:{cfg.daemon.port}"
    click.echo(f"Opening {url} ...")
    try:
        webbrowser.open(url)
    except Exception as exc:
        click.echo(f"  (could not open browser: {exc})")


# ---------------------------------------------------------------------------
# Internals — async store helpers
# ---------------------------------------------------------------------------


async def _query(
    *, source: str | None, status: EnvelopeStatus | None, limit: int
) -> list[Envelope]:
    cfg = load_config()
    store = Store(db_path=cfg.paths.data_dir / "loom.db")
    await store.init()
    try:
        return await store.query_envelopes(source=source, status=status, limit=limit)
    finally:
        await store.close()


async def _lookup(envelope_id: str) -> Envelope | None:
    cfg = load_config()
    store = Store(db_path=cfg.paths.data_dir / "loom.db")
    await store.init()
    try:
        env = await store.get_envelope(envelope_id)
        if env is not None:
            return env
        if len(envelope_id) >= 4:
            recent = await store.query_envelopes(limit=200)
            matches = [e for e in recent if e.id.startswith(envelope_id)]
            if len(matches) == 1:
                return matches[0]
        return None
    finally:
        await store.close()


async def _set_status(envelope_id: str, status: EnvelopeStatus) -> None:
    cfg = load_config()
    store = Store(db_path=cfg.paths.data_dir / "loom.db")
    await store.init()
    bus = EventBus()
    mailbox = Mailbox(store, bus)
    try:
        await mailbox.update_status(envelope_id, status)
    finally:
        await store.close()


async def _status_counts() -> dict[str, int]:
    cfg = load_config()
    store = Store(db_path=cfg.paths.data_dir / "loom.db")
    await store.init()
    try:
        envelopes = await store.query_envelopes(limit=10_000)
    finally:
        await store.close()
    return dict(Counter(str(e.status) for e in envelopes))


# ---------------------------------------------------------------------------
# Internals — doctor checks
# ---------------------------------------------------------------------------


def _check_loom_dir(config: LoomConfig) -> list[tuple[str, bool, str]]:
    rows: list[tuple[str, bool, str]] = [
        ("~/.loom directory", DEFAULT_LOOM_DIR.exists(), str(DEFAULT_LOOM_DIR)),
    ]
    for label, path in (
        ("policies dir", config.paths.policies_dir),
        ("prompts dir", config.paths.prompts_dir),
        ("data dir", config.paths.data_dir),
        ("credentials dir", config.paths.credentials_dir),
    ):
        rows.append((label, path.exists(), str(path)))
    return rows


def _check_config() -> list[tuple[str, bool, str]]:
    config_path = DEFAULT_LOOM_DIR / "config.yaml"
    if not config_path.exists():
        return [("config.yaml", False, f"missing at {config_path}")]
    try:
        cfg = load_config(config_path)
    except Exception as exc:
        return [("config.yaml", False, f"parse error: {exc}")]
    return [
        (
            "config.yaml",
            True,
            f"{len(cfg.sources)} source(s), daemon @ {cfg.daemon.host}:{cfg.daemon.port}",
        )
    ]


def _check_sources(config: LoomConfig) -> list[tuple[str, bool, str]]:
    if not config.sources:
        return [("sources configured", False, "none — try `loom source add github --repo ...`")]
    rows: list[tuple[str, bool, str]] = []
    for src in config.sources:
        kind = src.get("kind", "?")
        if kind == "github":
            ok = bool(os.environ.get("GITHUB_TOKEN"))
            rows.append(
                (
                    f"github · {src.get('owner')}/{src.get('repo')}",
                    ok,
                    "GITHUB_TOKEN set" if ok else "GITHUB_TOKEN not set",
                )
            )
        elif kind == "gmail":
            raw = src.get("client_secrets", "")
            secrets = Path(os.path.expanduser(raw)) if raw else None
            rows.append(
                (
                    "gmail credentials",
                    secrets is not None and secrets.exists(),
                    str(secrets) if secrets else "no client_secrets path",
                )
            )
        elif kind == "rss":
            url = src.get("url", "")
            rows.append((f"rss · {url}", bool(url), url or "no url"))
        elif kind == "anet":
            rows.append(("anet peer", True, src.get("peer", "(local)")))
        else:
            rows.append((f"{kind} source", False, "unknown kind"))
    return rows


def _check_database(config: LoomConfig) -> list[tuple[str, bool, str]]:
    db_path = config.paths.data_dir / "loom.db"
    if not db_path.exists():
        return [("loom.db", False, f"not yet created at {db_path}")]
    return [("loom.db", True, f"{db_path} · {_human_size(db_path.stat().st_size)}")]


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n //= 1024
    return f"{n}TB"
