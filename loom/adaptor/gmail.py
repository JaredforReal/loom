"""Gmail adaptor — IMAP / Google API."""

from __future__ import annotations

from typing import Any

from loom.adaptor.base import BaseAdaptor
from loom.core.envelope import Envelope


class GmailAdaptor(BaseAdaptor):
    """Watches Gmail inbox via IMAP IDLE or Google Pub/Sub push."""

    name = "gmail"

    async def start(self) -> None:
        # TODO: Authenticate and start watching
        pass

    async def stop(self) -> None:
        pass

    async def normalize(self, raw_event: Any) -> Envelope:
        # TODO: Parse email message → Envelope
        return Envelope(source=self.name)

    async def execute_action(self, envelope: Envelope, action: dict) -> None:
        # TODO: Send reply, archive, label, etc.
        pass
