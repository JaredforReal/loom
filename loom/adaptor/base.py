"""Base adaptor interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from loom.core.envelope import Envelope


class BaseAdaptor(ABC):
    """Abstract base for all external source adaptors.

    Subclasses must implement:
    - ``start`` / ``stop`` for lifecycle
    - ``normalize`` to convert raw events into Envelopes
    - ``execute_action`` to carry out user-approved actions
    """

    name: str = ""

    @abstractmethod
    async def start(self) -> None:
        """Start listening / polling the external source."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down the adaptor."""

    @abstractmethod
    async def normalize(self, raw_event: Any) -> Envelope:
        """Convert a raw external event into an Envelope."""

    @abstractmethod
    async def execute_action(self, envelope: Envelope, action: dict) -> None:
        """Execute an approved action back to the external source."""

    @property
    def is_running(self) -> bool:
        return False
