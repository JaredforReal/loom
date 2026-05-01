"""SQLite-backed state store for envelopes and session data."""

from __future__ import annotations

from pathlib import Path

from loom.core.envelope import Envelope, EnvelopeStatus


class Store:
    """Async SQLite store for envelopes.

    Uses SQLAlchemy + aiosqlite under the hood.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or Path.home() / ".loom" / "data" / "loom.db"

    async def init(self) -> None:
        """Create tables if they don't exist."""
        # TODO: SQLAlchemy table creation
        pass

    async def save_envelope(self, envelope: Envelope) -> None:
        # TODO: INSERT OR REPLACE into envelopes table
        pass

    async def get_envelope(self, envelope_id: str) -> Envelope | None:
        # TODO: SELECT by id
        return None

    async def query_envelopes(
        self,
        source: str | None = None,
        status: EnvelopeStatus | None = None,
        limit: int = 50,
    ) -> list[Envelope]:
        # TODO: SELECT with filters, ORDER BY received_at DESC
        return []

    async def get_unread_counts(self, source: str | None = None) -> dict[str, int]:
        """Return {source: count} for pending/waiting_approval envelopes."""
        # TODO: SELECT source, COUNT(*) WHERE status IN (pending, waiting_approval)
        return {}
