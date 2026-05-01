"""Agent Network (anet) adaptor — peer-to-peer agent messaging."""

from __future__ import annotations

from typing import Any

from loom.adaptor.base import BaseAdaptor
from loom.core.envelope import Envelope


class AnetAdaptor(BaseAdaptor):
    """Connects to an Agent Network for inter-agent messaging."""

    name = "anet"

    async def start(self) -> None:
        # TODO: Connect to anet peer / message broker
        pass

    async def stop(self) -> None:
        pass

    async def normalize(self, raw_event: Any) -> Envelope:
        # TODO: Parse anet message → Envelope
        return Envelope(source=self.name)

    async def execute_action(self, envelope: Envelope, action: dict) -> None:
        # TODO: Send reply to anet peer
        pass
