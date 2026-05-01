"""Rich renderers for envelopes and diagnostic reports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from rich.box import SIMPLE_HEAVY
from rich.console import Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from loom.cli.view.theme import (
    priority_label,
    priority_style,
    source_stamp,
    source_style,
    status_glyph,
    status_style,
)
from loom.core.envelope import Envelope


def _relative_time(ts: datetime | None) -> str:
    """Render ``ts`` as ``5m`` / ``2h`` / ``3d``, or ISO date for older."""
    if ts is None:
        return "—"
    now = datetime.now(UTC)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    seconds = int((now - ts).total_seconds())
    if seconds < 60:
        return f"{max(seconds, 0)}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    if seconds < 7 * 86400:
        return f"{seconds // 86400}d"
    return ts.strftime("%Y-%m-%d")


def envelope_table(envelopes: list[Envelope], *, title: str = "Inbox") -> Table:
    """Render a list of envelopes as the standard Loom inbox table."""
    table = Table(
        title=title,
        title_style="panel.title",
        header_style="table.header",
        box=SIMPLE_HEAVY,
        expand=True,
        show_lines=False,
    )
    table.add_column("", width=2)
    table.add_column("id", style="loom.muted", width=8, no_wrap=True)
    table.add_column("src", width=4, no_wrap=True)
    table.add_column("pri", width=3, no_wrap=True)
    table.add_column("title", ratio=1, no_wrap=False)
    table.add_column("labels", style="loom.muted", no_wrap=True)
    table.add_column("age", width=5, no_wrap=True, justify="right")

    for env in envelopes:
        table.add_row(
            Text(status_glyph(env.status), style=status_style(env.status)),
            env.id[:8],
            Text(source_stamp(env.source), style=source_style(env.source)),
            Text(priority_label(env.priority), style=priority_style(env.priority)),
            env.title or "(untitled)",
            ", ".join(env.labels[:3]),
            _relative_time(env.received_at),
        )
    if not envelopes:
        table.add_row("", "", "", "", Text("(no messages)", style="hint"), "", "")
    return table


def envelope_detail(env: Envelope) -> Group:
    """Render a multi-panel detail view for a single envelope."""
    header = Text()
    header.append(status_glyph(env.status) + " ", style=status_style(env.status))
    header.append(priority_label(env.priority) + " ", style=priority_style(env.priority))
    header.append(source_stamp(env.source) + " ", style=source_style(env.source))
    header.append(env.title or "(untitled)", style="loom.accent")

    meta_lines: list[Text] = [
        _kv("id", env.id),
        _kv("source", f"{env.source}   source_id={env.source_id}"),
        _kv("status", str(env.status)),
        _kv("received", str(env.received_at)),
    ]
    if env.labels:
        meta_lines.append(_kv("labels", ", ".join(env.labels)))
    for key in sorted(env.metadata.keys()):
        meta_lines.append(_kv(f"meta.{key}", str(env.metadata[key])))

    meta_panel = Panel(
        Group(*meta_lines),
        title="envelope",
        title_align="left",
        border_style="panel.border",
    )
    body_panel = Panel(
        Text(env.body or "(empty body)", style="value"),
        title="body",
        title_align="left",
        border_style="panel.border",
    )

    panels: list[Any] = [header, meta_panel, body_panel]
    log_panel = _agent_log_panel(env.agent_log)
    if log_panel is not None:
        panels.append(log_panel)
    action_panel = _proposed_action_panel(env.proposed_action)
    if action_panel is not None:
        panels.append(action_panel)
    return Group(*panels)


def _kv(key: str, value: str) -> Text:
    text = Text()
    text.append(f"{key:>12}  ", style="key")
    text.append(value, style="value")
    return text


def _agent_log_panel(log: list[dict]) -> Panel | None:
    if not log:
        return None
    lines: list[Text] = []
    for step in log:
        name = str(step.get("step", ""))
        out = str(step.get("output", "") or step.get("input", ""))
        line = Text()
        line.append(f"{name:>14}  ", style="loom.muted")
        line.append(out[:120] + ("…" if len(out) > 120 else ""), style="value")
        lines.append(line)
    return Panel(
        Group(*lines),
        title="agent log",
        title_align="left",
        border_style="panel.border",
    )


def _proposed_action_panel(action: dict | None) -> Panel | None:
    if not action:
        return None
    pretty = json.dumps(action, indent=2, sort_keys=True, default=str)
    return Panel(
        Syntax(pretty, "json", theme="ansi_dark", background_color="default"),
        title="proposed action",
        title_align="left",
        border_style="panel.border",
    )


def status_bar(info: dict[str, Any]) -> Text:
    """One-line daemon status indicator."""
    online = bool(info.get("online"))
    bar = Text()
    bar.append("  loom  ", style="loom.brand")
    bar.append("●" if online else "○", style="loom.ok" if online else "loom.warn")
    bar.append(f"  daemon {'up' if online else 'down'}  ", style="value")
    bar.append(f"· active {info.get('active_sessions', 0)}  ", style="loom.muted")
    bar.append(f"· queued {info.get('queue_backlog', 0)}  ", style="loom.muted")
    cost = info.get("cost_today_usd")
    if cost is not None:
        bar.append(f"· ${cost:.2f} today", style="loom.muted")
    return bar


def doctor_report(checks: list[tuple[str, bool, str]]) -> Table:
    """Render ``[(name, ok, detail), ...]`` as a check-list table."""
    table = Table(
        title="loom doctor",
        title_style="panel.title",
        header_style="table.header",
        box=SIMPLE_HEAVY,
        expand=True,
    )
    table.add_column("", width=2)
    table.add_column("check", no_wrap=True)
    table.add_column("detail", style="loom.muted")
    for name, ok, detail in checks:
        glyph = Text("✓", style="loom.ok") if ok else Text("✗", style="loom.error")
        table.add_row(glyph, name, detail)
    return table
