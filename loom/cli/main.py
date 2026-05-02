"""Loom CLI — argparse parser + command handlers.

Bridges user invocations to the mailbox / store layer. Each ``cmd_*``
parses an argparse Namespace, loads or mutates envelopes through the
Store, and renders results via the view layer.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import webbrowser
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import NoReturn

from loom.cli.view.render import doctor_report, envelope_detail, envelope_table, status_bar
from loom.cli.view.theme import make_console
from loom.config import DEFAULT_LOOM_DIR, LoomConfig, load_config, save_config
from loom.core.envelope import Envelope, EnvelopeStatus
from loom.core.eventbus import EventBus
from loom.core.mailbox import Mailbox
from loom.state.store import Store


def _load_dotenv() -> None:
    """Load .env from CWD and ~/.loom/ into os.environ (no overwrite)."""
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


# ------------------------------------------------------------------
# Parser
# ------------------------------------------------------------------


def _version() -> str:
    try:
        return version("loom")
    except PackageNotFoundError:
        return "0.0.0"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loom",
        description="Loom — Mailbox and agent orchestration for Claude Code.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"loom {_version()}",
    )
    commands = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="COMMAND",
    )

    # ---- inbox ----
    inbox = commands.add_parser("inbox", help="List envelopes — newest first.")
    inbox.add_argument(
        "--source",
        type=str,
        required=False,
        default=None,
        help="Filter by source (github, gmail, rss, anet)",
    )
    inbox.add_argument(
        "--status",
        type=str,
        required=False,
        default=None,
        choices=[str(s) for s in EnvelopeStatus],
        help="Filter by envelope status",
    )
    inbox.add_argument(
        "--limit",
        type=int,
        required=False,
        default=50,
        help="Max rows to show (default: 50)",
    )
    inbox.set_defaults(func=cmd_inbox)

    # ---- show ----
    show = commands.add_parser("show", help="Show a single envelope by id (or 8-char prefix).")
    show.add_argument(
        "envelope_id",
        type=str,
        help="Envelope id or unique 8-char prefix",
    )
    show.set_defaults(func=cmd_show)

    # ---- approve ----
    approve = commands.add_parser("approve", help="Approve the proposed action on an envelope.")
    approve.add_argument(
        "envelope_id",
        type=str,
        help="Envelope id or unique 8-char prefix",
    )
    approve.set_defaults(func=cmd_approve)

    # ---- reject ----
    reject = commands.add_parser("reject", help="Reject the proposed action; mark dismissed.")
    reject.add_argument(
        "envelope_id",
        type=str,
        help="Envelope id or unique 8-char prefix",
    )
    reject.add_argument(
        "--reason",
        type=str,
        required=False,
        default="",
        help="Optional reason recorded with the rejection",
    )
    reject.set_defaults(func=cmd_reject)

    # ---- daemon ----
    daemon = commands.add_parser("daemon", help="Start the Loom daemon.")
    daemon.set_defaults(func=cmd_daemon)

    # ---- status ----
    status = commands.add_parser("status", help="Show queue backlog and envelope status counts.")
    status.set_defaults(func=cmd_status)

    # ---- doctor ----
    doctor = commands.add_parser("doctor", help="Diagnose the local Loom setup.")
    doctor.set_defaults(func=cmd_doctor)

    # ---- ui ----
    ui = commands.add_parser("ui", help="Open the Loom web UI in a browser.")
    ui.set_defaults(func=cmd_ui)

    # ---- source (group) ----
    source = commands.add_parser("source", help="Manage external sources.")
    source_actions = source.add_subparsers(
        dest="source_command",
        required=True,
        metavar="ACTION",
    )

    # source add
    source_add = source_actions.add_parser("add", help="Add a new source subscription.")
    source_add.add_argument(
        "kind",
        type=str,
        choices=["github", "rss", "gmail", "anet"],
        help="Source kind to add",
    )
    source_add.add_argument(
        "--repo",
        type=str,
        action="append",
        required=False,
        default=[],
        help="GitHub repo (owner/repo); may be given multiple times",
    )
    source_add.add_argument(
        "--events",
        type=str,
        required=False,
        default="issues,pull_requests",
        help="GitHub events to track (comma-separated)",
    )
    source_add.add_argument(
        "--interval",
        type=int,
        required=False,
        default=120,
        help="Poll interval in seconds",
    )
    source_add.add_argument(
        "--state",
        type=str,
        required=False,
        default="all",
        help="Issue/PR state filter (open, closed, all)",
    )
    source_add.add_argument(
        "--url",
        type=str,
        required=False,
        default=None,
        help="Feed URL (RSS)",
    )
    source_add.add_argument(
        "--credentials",
        type=str,
        required=False,
        default=None,
        help="Path to credentials file",
    )
    source_add.add_argument(
        "--token",
        type=str,
        required=False,
        default=None,
        help="GitHub personal access token (or set GITHUB_TOKEN env)",
    )
    source_add.set_defaults(func=cmd_source_add)

    # source list
    source_list = source_actions.add_parser("list", help="List configured sources.")
    source_list.set_defaults(func=cmd_source_list)

    return parser


def cli(argv: list[str] | None = None) -> int:
    _load_dotenv()
    args = _build_parser().parse_args(argv)
    args.func(args)
    return 0


# ------------------------------------------------------------------
# Envelope commands
# ------------------------------------------------------------------


def cmd_inbox(args: argparse.Namespace) -> None:
    """List envelopes — newest first."""
    envelopes = asyncio.run(_load_inbox(args))
    make_console().print(envelope_table(envelopes))


def cmd_show(args: argparse.Namespace) -> None:
    """Show a single envelope by id (or 8-char prefix)."""
    envelope = _require_envelope(args.envelope_id)
    make_console().print(envelope_detail(envelope))


def cmd_approve(args: argparse.Namespace) -> None:
    """Approve the proposed action on an envelope."""
    envelope = _require_envelope(args.envelope_id)
    asyncio.run(_set_status(envelope.id, EnvelopeStatus.DONE))
    print(f"  Approved: {envelope.id[:8]}")


def cmd_reject(args: argparse.Namespace) -> None:
    """Reject the proposed action; the envelope is marked dismissed."""
    envelope = _require_envelope(args.envelope_id)
    asyncio.run(_set_status(envelope.id, EnvelopeStatus.DISMISSED))
    suffix = f" ({args.reason})" if args.reason else ""
    print(f"  Rejected: {envelope.id[:8]}{suffix}")


# ------------------------------------------------------------------
# System commands
# ------------------------------------------------------------------


def cmd_daemon(args: argparse.Namespace) -> None:
    """Start the Loom daemon (mailbox + dispatcher + web UI)."""
    print("Starting Loom daemon...")
    os.execvp(sys.executable, [sys.executable, "-m", "loom.daemon"])


def cmd_status(args: argparse.Namespace) -> None:
    """Show queue backlog and envelope status counts."""
    config = load_config()
    pid_path = config.paths.data_dir / "loom.pid"
    online = False
    daemon_info = {"online": False, "active_sessions": 0, "queue_backlog": 0}

    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            os.kill(pid, 0)
            online = True
            daemon_info["online"] = True
        except (ProcessLookupError, ValueError):
            pass

    counts = asyncio.run(_load_status_counts())
    backlog = counts.get(str(EnvelopeStatus.PENDING), 0) + counts.get(
        str(EnvelopeStatus.PROCESSING), 0
    )
    daemon_info["queue_backlog"] = backlog

    console = make_console()
    console.print(status_bar(daemon_info))
    for status, n in sorted(counts.items()):
        console.print(f"  {status:<20} {n}", style="loom.muted")
    if online:
        console.print(f"  daemon pid={pid}", style="loom.muted")
    else:
        console.print("  daemon: not running", style="loom.muted")


def cmd_ui(args: argparse.Namespace) -> None:
    """Open the Loom web UI in a browser."""
    cfg = load_config()
    url = f"http://{cfg.daemon.host}:{cfg.daemon.port}"
    print(f"Opening {url} ...")
    try:
        webbrowser.open(url)
    except Exception as exc:
        print(f"  (could not open browser: {exc})")


# ------------------------------------------------------------------
# Source management
# ------------------------------------------------------------------


def cmd_source_add(args: argparse.Namespace) -> None:
    """Add a new source subscription."""
    config = load_config()
    if args.kind == "github":
        _add_github_source(config, args)
    elif args.kind == "gmail":
        _add_gmail_source(config, args)
    elif args.kind == "rss":
        _add_rss_source(config, args)
    elif args.kind == "anet":
        _add_anet_source(config, args)
    save_config(config)


def cmd_source_list(args: argparse.Namespace) -> None:
    """List configured sources."""
    config = load_config()
    if not config.sources:
        print("No sources configured. Use `loom source add <kind>` to add one.")
        return
    for i, src in enumerate(config.sources, 1):
        kind = src.get("kind", "unknown")
        print(f"  {i}. [{kind}] {_describe_source(src)}")


def _add_github_source(config: LoomConfig, args: argparse.Namespace) -> None:
    if not args.repo:
        _die("--repo is required for GitHub sources (e.g. --repo owner/repo)")
    events = [e.strip() for e in args.events.split(",")]
    for repo in args.repo:
        if repo.count("/") != 1:
            _die(f"Invalid repo format '{repo}' — expected 'owner/repo'")
        owner, name = repo.split("/")
        config.sources.append(
            {
                "kind": "github",
                "owner": owner,
                "repo": name,
                "poll_interval": args.interval,
                "events": events,
                "state": args.state,
            }
        )
        print(f"  Added: {repo} (events={events}, interval={args.interval}s, state={args.state})")
    tok = "provided" if args.token else "GITHUB_TOKEN env"
    print(f"\nGitHub source(s) saved to config. Token: {tok}")
    print("Run `loom daemon` to start monitoring.")


def _add_gmail_source(config: LoomConfig, args: argparse.Namespace) -> None:
    config.sources.append(
        {
            "kind": "gmail",
            "client_secrets": args.credentials or "~/.loom/credentials/gmail-client-secrets.json",
        }
    )
    print("Gmail source saved to config.")
    print("Run `loom daemon` to start monitoring.")


def _add_rss_source(config: LoomConfig, args: argparse.Namespace) -> None:
    if not args.url:
        _die("--url is required for RSS sources")
    config.sources.append({"kind": "rss", "url": args.url})
    print(f"RSS source saved: {args.url}")


def _add_anet_source(config: LoomConfig, args: argparse.Namespace) -> None:
    config.sources.append({"kind": "anet"})
    print("Anet source saved to config.")


def _describe_source(src: dict[str, object]) -> str:
    kind = src.get("kind")
    if kind == "github":
        return f"{src.get('owner', '?')}/{src.get('repo', '?')}"
    if kind == "gmail":
        return f"Gmail ({src.get('query', 'is:unread')})"
    if kind == "rss":
        return str(src.get("url", "unknown"))
    return str(src)


# ------------------------------------------------------------------
# Doctor
# ------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> None:
    """Diagnose the local Loom setup."""
    config = load_config()
    checks = [
        *_check_loom_dir(config),
        *_check_config(),
        *_check_sources(config),
        *_check_database(config),
    ]
    make_console().print(doctor_report(checks))
    if any(not ok for _, ok, _ in checks):
        raise SystemExit(1)


def _check_loom_dir(config: LoomConfig) -> list[tuple[str, bool, str]]:
    rows = [("~/.loom directory", DEFAULT_LOOM_DIR.exists(), str(DEFAULT_LOOM_DIR))]
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
    detail = f"{len(cfg.sources)} source(s), daemon @ {cfg.daemon.host}:{cfg.daemon.port}"
    return [("config.yaml", True, detail)]


def _check_sources(config: LoomConfig) -> list[tuple[str, bool, str]]:
    if not config.sources:
        return [("sources configured", False, "none — try `loom source add github --repo ...`")]
    return [_check_one_source(src) for src in config.sources]


def _check_one_source(src: dict[str, object]) -> tuple[str, bool, str]:
    kind = src.get("kind")
    if kind == "github":
        ok = bool(os.environ.get("GITHUB_TOKEN"))
        label = f"github · {src.get('owner')}/{src.get('repo')}"
        detail = "GITHUB_TOKEN set" if ok else "GITHUB_TOKEN not set"
        return (label, ok, detail)
    if kind == "gmail":
        raw = src.get("client_secrets") or ""
        secrets = Path(os.path.expanduser(str(raw))) if raw else None
        return (
            "gmail credentials",
            secrets is not None and secrets.exists(),
            str(secrets) if secrets else "no client_secrets path",
        )
    if kind == "rss":
        url = str(src.get("url", ""))
        return (f"rss · {url}", bool(url), url or "no url")
    if kind == "anet":
        return ("anet peer", True, str(src.get("peer", "(local)")))
    return (f"{kind} source", False, "unknown kind")


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


# ------------------------------------------------------------------
# Internals — store access
# ------------------------------------------------------------------


@asynccontextmanager
async def _open_store() -> AsyncIterator[Store]:
    store = Store(db_path=load_config().paths.data_dir / "loom.db")
    await store.init()
    try:
        yield store
    finally:
        await store.close()


async def _load_inbox(args: argparse.Namespace) -> list[Envelope]:
    async with _open_store() as store:
        return await store.query_envelopes(
            source=args.source,
            status=EnvelopeStatus(args.status) if args.status else None,
            limit=args.limit,
        )


async def _load_status_counts() -> dict[str, int]:
    async with _open_store() as store:
        envelopes = await store.query_envelopes(limit=10_000)
    return dict(Counter(str(env.status) for env in envelopes))


async def _lookup(envelope_id: str) -> Envelope | None:
    async with _open_store() as store:
        env = await store.get_envelope(envelope_id)
        if env is not None:
            return env
        if len(envelope_id) >= 4:
            recent = await store.query_envelopes(limit=200)
            matches = [e for e in recent if e.id.startswith(envelope_id)]
            if len(matches) == 1:
                return matches[0]
        return None


async def _set_status(envelope_id: str, status: EnvelopeStatus) -> None:
    async with _open_store() as store:
        await Mailbox(store, EventBus()).update_status(envelope_id, status)


def _require_envelope(envelope_id: str) -> Envelope:
    env = asyncio.run(_lookup(envelope_id))
    if env is None:
        _die(f"no envelope matching '{envelope_id}'")
    return env


def _die(msg: str) -> NoReturn:
    print(f"Error: {msg}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    sys.exit(cli())
