"""Event — a tracked item that accumulates updates over time."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Event:
    """A tracked item with accumulated updates and persistent agent session."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str = ""  # "owner/repo#42"
    source: str = ""  # "github"
    title: str = ""
    group: str = ""
    envelope_id: str = ""  # original envelope that was tracked
    status: str = "active"  # "active" | "resolved"
    agent_session_id: str = ""
    agent_summary: str = ""
    labels: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    updates: list[dict] = field(default_factory=list)  # [{id, type, author, body, ...}]
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
