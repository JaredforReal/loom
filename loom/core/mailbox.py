"""Mailbox — receives, stores, and dispatches envelopes."""

from __future__ import annotations

from loom.core.envelope import Envelope, EnvelopeStatus
from loom.core.eventbus import EventBus
from loom.state.store import Store


class Mailbox:
    """Central mailbox that coordinates incoming envelopes.

    1. Accepts an envelope from an adaptor
    2. Persists it via the state store
    3. Publishes a ``new_envelope`` event on the bus
    """

    def __init__(self, store: Store, bus: EventBus) -> None:
        self._store = store
        self._bus = bus

    async def receive(self, envelope: Envelope) -> Envelope:
        """Accept a new envelope from an adaptor."""
        envelope.status = EnvelopeStatus.PENDING
        await self._store.save_envelope(envelope)
        await self._bus.publish("new_envelope", envelope)
        return envelope

    async def update_status(self, envelope_id: str, status: EnvelopeStatus) -> Envelope | None:
        """Transition an envelope to a new status."""
        envelope = await self._store.get_envelope(envelope_id)
        if envelope is None:
            return None
        envelope.status = status
        await self._store.save_envelope(envelope)
        await self._bus.publish("envelope_status_changed", envelope)
        return envelope

    async def list_envelopes(
        self,
        source: str | None = None,
        status: EnvelopeStatus | None = None,
        group: str | None = None,
        limit: int = 50,
    ) -> list[Envelope]:
        """Query envelopes with optional filters."""
        return await self._store.query_envelopes(
            source=source, status=status, group=group, limit=limit
        )

    async def get_unread_count(self, source: str | None = None) -> dict[str, int]:
        """Get unread counts, optionally grouped by source."""
        return await self._store.get_unread_counts(source=source)
