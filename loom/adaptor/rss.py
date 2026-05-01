"""RSS/Atom feed adaptor."""

from __future__ import annotations

from typing import Any

from loom.adaptor.base import BaseAdaptor
from loom.core.envelope import Envelope


class RSSAdaptor(BaseAdaptor):
    """Polls RSS/Atom feeds on a configurable interval."""

    name = "rss"

    async def start(self) -> None:
        # TODO: Set up polling scheduler via APScheduler
        pass

    async def stop(self) -> None:
        pass

    async def normalize(self, raw_event: Any) -> Envelope:
        # TODO: Parse feedparser entry → Envelope
        return Envelope(source=self.name)

    async def execute_action(self, envelope: Envelope, action: dict) -> None:
        # RSS is read-only; no actions to execute
        pass
