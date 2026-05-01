"""Rich theme and visual language for the Loom CLI.

Single source of truth for colours, status glyphs, priority badges and
per-source stamps.  Every renderer imports symbols from here instead of
hard-coding colour strings, so the look can be retuned in one place.

The palette leans warm (amber / cream / rust) so Loom has its own visual
identity — distinct from Claude Code's cool blues.
"""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

from loom.core.envelope import EnvelopeStatus

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

LOOM_THEME = Theme(
    {
        # Brand
        "loom.brand": "bold #ffb347",  # amber
        "loom.accent": "#ffdead",  # cream
        "loom.muted": "grey50",
        "loom.dim": "grey39",
        "loom.warn": "bold #d2691e",  # rust
        "loom.error": "bold red",
        "loom.ok": "bold green",
        # Status
        "status.pending": "#c0c0c0",
        "status.processing": "#ffd700",
        "status.waiting": "bold #ffb347",
        "status.done": "green",
        "status.dismissed": "grey42",
        "status.failed": "bold red",
        # Priority
        "priority.p0": "grey50",
        "priority.p1": "#87afff",
        "priority.p2": "#ffd75f",
        "priority.p3": "bold red",
        # Sources (the "stamps")
        "source.github": "#c792ea",  # purple
        "source.gmail": "#ff5f87",  # red
        "source.rss": "#ff8700",  # orange
        "source.anet": "#5fd7d7",  # cyan
        "source.unknown": "grey50",
        # UI chrome
        "panel.border": "#ffb347",
        "panel.title": "bold #ffdead",
        "table.header": "bold #ffb347",
        "key": "bold #ffdead",
        "value": "white",
        "hint": "italic grey50",
    }
)


def make_console() -> Console:
    """Return a Console with the Loom theme applied."""
    return Console(theme=LOOM_THEME, highlight=False)


# ---------------------------------------------------------------------------
# Glyph / style maps
# ---------------------------------------------------------------------------

STATUS_GLYPH: dict[EnvelopeStatus, str] = {
    EnvelopeStatus.PENDING: "●",
    EnvelopeStatus.PROCESSING: "◐",
    EnvelopeStatus.WAITING_APPROVAL: "◑",
    EnvelopeStatus.DONE: "✓",
    EnvelopeStatus.DISMISSED: "✗",
    EnvelopeStatus.FAILED: "✗",
}

STATUS_STYLE: dict[EnvelopeStatus, str] = {
    EnvelopeStatus.PENDING: "status.pending",
    EnvelopeStatus.PROCESSING: "status.processing",
    EnvelopeStatus.WAITING_APPROVAL: "status.waiting",
    EnvelopeStatus.DONE: "status.done",
    EnvelopeStatus.DISMISSED: "status.dismissed",
    EnvelopeStatus.FAILED: "status.failed",
}

PRIORITY_LABEL: dict[int, str] = {0: "P0", 1: "P1", 2: "P2", 3: "P3"}
PRIORITY_STYLE: dict[int, str] = {
    0: "priority.p0",
    1: "priority.p1",
    2: "priority.p2",
    3: "priority.p3",
}

SOURCE_STAMP: dict[str, str] = {
    "github": "GH",
    "gmail": "✉",
    "rss": "»",
    "anet": "⚯",
}


def status_style(status: EnvelopeStatus) -> str:
    return STATUS_STYLE.get(status, "loom.muted")


def status_glyph(status: EnvelopeStatus) -> str:
    return STATUS_GLYPH.get(status, "·")


def priority_label(priority: int) -> str:
    return PRIORITY_LABEL.get(priority, f"P{priority}")


def priority_style(priority: int) -> str:
    return PRIORITY_STYLE.get(priority, "priority.p1")


def source_stamp(source: str) -> str:
    return SOURCE_STAMP.get(source, source[:2].upper() if source else "··")


def source_style(source: str) -> str:
    return f"source.{source}" if source in SOURCE_STAMP else "source.unknown"
