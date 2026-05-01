"""Envelope — the universal message unit."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class EnvelopeStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    WAITING_APPROVAL = "waiting_approval"
    DONE = "done"
    DISMISSED = "dismissed"
    FAILED = "failed"


@dataclass
class Envelope:
    """A normalized message from any external source."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str = ""  # "github", "rss", "gmail", "anet"
    source_id: str = ""  # External ID (e.g. issue #42)
    title: str = ""
    body: str = ""  # Raw payload
    received_at: datetime = field(default_factory=datetime.utcnow)
    status: EnvelopeStatus = EnvelopeStatus.PENDING
    priority: int = 1  # 0=low, 1=normal, 2=high, 3=urgent
    labels: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    # Processing results (filled by agent)
    agent_summary: str = ""
    agent_log: list[dict] = field(default_factory=list)  # [{step, input, output, ts}]
    proposed_action: dict | None = None  # Action awaiting user approval
