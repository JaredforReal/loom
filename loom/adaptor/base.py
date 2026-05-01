"""Base adaptor interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from loom.core.envelope import Envelope

# Callback that adaptors use to feed envelopes into the mailbox
OnEnvelopeCallback = Callable[[Envelope], Awaitable[None]]


class BaseAdaptor(ABC):
    """Abstract base for all external source adaptors.

    Subclasses must implement:
    - ``start`` / ``stop`` for lifecycle
    - ``normalize`` to convert raw events into Envelopes
    - ``execute_action`` to carry out user-approved actions

    The ``on_envelope`` callback is set by the orchestrator before
    ``start()`` is called.  Adaptors call it to feed new envelopes
    into the mailbox.
    """

    name: str = ""
    _on_envelope: OnEnvelopeCallback | None = None

    def set_callback(self, callback: OnEnvelopeCallback) -> None:
        """Set the callback used to deliver envelopes to the mailbox."""
        self._on_envelope = callback

    async def _emit(self, envelope: Envelope) -> None:
        """Deliver an envelope to the mailbox via the callback."""
        if self._on_envelope is None:
            raise RuntimeError(
                f"Adaptor {self.name} has no on_envelope callback — "
                "call set_callback() before start()"
            )
        await self._on_envelope(envelope)

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
