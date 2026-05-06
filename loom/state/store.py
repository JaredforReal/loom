"""SQLite-backed state store for envelopes and adaptor state."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import Column, DateTime, Integer, String, Text, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from loom.core.envelope import Envelope, EnvelopeStatus
from loom.core.event import Event

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class EnvelopeRow(Base):
    __tablename__ = "envelopes"

    id = Column(String, primary_key=True)
    source = Column(String, index=True)
    source_id = Column(String, index=True)
    title = Column(Text, default="")
    body = Column(Text, default="")
    received_at = Column(DateTime, index=True)
    status = Column(String, default="pending")
    priority = Column(Integer, default=1)
    labels = Column(Text, default="[]")
    group = Column(String, index=True, default="")
    metadata_ = Column("metadata", Text, default="{}")
    agent_summary = Column(Text, default="")
    agent_log = Column(Text, default="[]")
    proposed_action = Column(Text, nullable=True)


class AdaptorStateRow(Base):
    __tablename__ = "adaptor_state"

    adaptor = Column(String, primary_key=True)
    key = Column(String, primary_key=True)
    value = Column(Text, default="")


class EventRow(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True)
    source_id = Column(String, unique=True, index=True)
    source = Column(String, index=True)
    title = Column(Text)
    group_col = Column("group", String, index=True, default="")
    envelope_id = Column(String)
    status = Column(String, default="active")
    agent_session_id = Column(String, default="")
    agent_summary = Column(Text, default="")
    labels = Column(Text, default="[]")
    metadata_ = Column("metadata", Text, default="{}")
    updates = Column(Text, default="[]")
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


def _row_to_envelope(row: EnvelopeRow) -> Envelope:
    """Convert a database row to an Envelope dataclass."""
    return Envelope(
        id=row.id,
        source=row.source or "",
        source_id=row.source_id or "",
        title=row.title or "",
        body=row.body or "",
        received_at=row.received_at or datetime.utcnow(),
        status=EnvelopeStatus(row.status) if row.status else EnvelopeStatus.PENDING,
        priority=row.priority or 1,
        labels=json.loads(row.labels) if row.labels else [],
        group=row.group or "",
        metadata=json.loads(row.metadata_) if row.metadata_ else {},
        agent_summary=row.agent_summary or "",
        agent_log=json.loads(row.agent_log) if row.agent_log else [],
        proposed_action=json.loads(row.proposed_action) if row.proposed_action else None,
    )


def _envelope_to_row(env: Envelope, row: EnvelopeRow | None = None) -> EnvelopeRow:
    """Convert an Envelope dataclass to a database row."""
    if row is None:
        row = EnvelopeRow()
    row.id = env.id
    row.source = env.source
    row.source_id = env.source_id
    row.title = env.title
    row.body = env.body
    row.received_at = env.received_at
    row.status = str(env.status)
    row.priority = env.priority
    row.labels = json.dumps(env.labels)
    row.group = env.group
    row.metadata_ = json.dumps(env.metadata)
    row.agent_summary = env.agent_summary
    row.agent_log = json.dumps(env.agent_log)
    row.proposed_action = (
        json.dumps(env.proposed_action) if env.proposed_action is not None else None
    )
    return row


def _row_to_event(row: EventRow) -> Event:
    """Convert a database row to an Event dataclass."""
    return Event(
        id=row.id,
        source_id=row.source_id or "",
        source=row.source or "",
        title=row.title or "",
        group=row.group_col or "",
        envelope_id=row.envelope_id or "",
        status=row.status or "active",
        agent_session_id=row.agent_session_id or "",
        agent_summary=row.agent_summary or "",
        labels=json.loads(row.labels) if row.labels else [],
        metadata=json.loads(row.metadata_) if row.metadata_ else {},
        updates=json.loads(row.updates) if row.updates else [],
        created_at=row.created_at or datetime.utcnow(),
        updated_at=row.updated_at or datetime.utcnow(),
    )


def _event_to_row(event: Event, row: EventRow | None = None) -> EventRow:
    """Convert an Event dataclass to a database row."""
    if row is None:
        row = EventRow()
    row.id = event.id
    row.source_id = event.source_id
    row.source = event.source
    row.title = event.title
    row.group_col = event.group
    row.envelope_id = event.envelope_id
    row.status = event.status
    row.agent_session_id = event.agent_session_id
    row.agent_summary = event.agent_summary
    row.labels = json.dumps(event.labels)
    row.metadata_ = json.dumps(event.metadata)
    row.updates = json.dumps(event.updates)
    row.created_at = event.created_at
    row.updated_at = event.updated_at
    return row


class Store:
    """Async SQLite store for envelopes and adaptor state.

    Uses SQLAlchemy + aiosqlite under the hood.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or Path.home() / ".loom" / "data" / "loom.db"
        self._engine = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def init(self) -> None:
        """Create tables if they don't exist. Safe to call multiple times."""
        if self._session_factory is not None:
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_async_engine(
            f"sqlite+aiosqlite:///{self._db_path}",
            echo=False,
        )
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Migrate existing DBs that predate the group column
            try:
                await conn.execute(
                    text("ALTER TABLE envelopes ADD COLUMN \"group\" TEXT DEFAULT ''")
                )
            except Exception:
                pass  # Column already exists
            # Migrate: rename old status value waiting_approval -> in_review
            await conn.execute(
                text("UPDATE envelopes SET status = 'in_review' WHERE status = 'waiting_approval'")
            )
            # Migrate: reset GitHub envelope groups to source_id-derived value
            # (undoes any stale backfill from previous daemon runs)
            await conn.execute(
                text(
                    'UPDATE envelopes SET "group" = '
                    "substr(source_id, 1, instr(source_id, '#') - 1) "
                    "WHERE source = 'github' AND source_id LIKE '%#%'"
                )
            )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        logger.info("Store initialized at %s", self._db_path)

    async def close(self) -> None:
        """Dispose of the database engine."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    def _session(self) -> AsyncSession:
        if self._session_factory is None:
            raise RuntimeError("Store not initialized — call init() first")
        return self._session_factory()

    async def save_envelope(self, envelope: Envelope) -> None:
        """Insert or update an envelope."""
        async with self._session() as session:
            existing = await session.get(EnvelopeRow, envelope.id)
            row = _envelope_to_row(envelope, existing)
            session.add(row)
            await session.commit()

    async def get_envelope(self, envelope_id: str) -> Envelope | None:
        """Retrieve a single envelope by ID."""
        async with self._session() as session:
            row = await session.get(EnvelopeRow, envelope_id)
            if row is None:
                return None
            return _row_to_envelope(row)

    async def query_envelopes(
        self,
        source: str | None = None,
        status: EnvelopeStatus | None = None,
        group: str | None = None,
        source_id_prefix: str | None = None,
        source_id_prefixes: list[str] | None = None,
        limit: int = 50,
    ) -> list[Envelope]:
        """Query envelopes with optional filters, newest first."""
        async with self._session() as session:
            stmt = select(EnvelopeRow).order_by(EnvelopeRow.received_at.desc())
            if source is not None:
                stmt = stmt.where(EnvelopeRow.source == source)
            if status is not None:
                stmt = stmt.where(EnvelopeRow.status == str(status))
            if group is not None:
                stmt = stmt.where(EnvelopeRow.group == group)
            if source_id_prefix is not None:
                stmt = stmt.where(EnvelopeRow.source_id.startswith(source_id_prefix))
            if source_id_prefixes:
                from sqlalchemy import or_

                stmt = stmt.where(
                    or_(*(EnvelopeRow.source_id.startswith(p) for p in source_id_prefixes))
                )
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [_row_to_envelope(r) for r in rows]

    async def get_unread_counts(self, source: str | None = None) -> dict[str, int]:
        """Return {source: count} for pending/in_review envelopes."""
        async with self._session() as session:
            stmt = (
                select(EnvelopeRow.source, func.count(EnvelopeRow.id))
                .where(
                    EnvelopeRow.status.in_(
                        [
                            str(EnvelopeStatus.PENDING),
                            str(EnvelopeStatus.IN_REVIEW),
                        ]
                    )
                )
                .group_by(EnvelopeRow.source)
            )
            if source is not None:
                stmt = stmt.where(EnvelopeRow.source == source)
            result = await session.execute(stmt)
            return {row[0]: row[1] for row in result.all()}

    async def get_unread_counts_by_group(self) -> dict[str, int]:
        """Return {group: count} for pending/in_review envelopes."""
        async with self._session() as session:
            stmt = (
                select(EnvelopeRow.group, func.count(EnvelopeRow.id))
                .where(
                    EnvelopeRow.status.in_(
                        [
                            str(EnvelopeStatus.PENDING),
                            str(EnvelopeStatus.IN_REVIEW),
                        ]
                    )
                )
                .where(EnvelopeRow.group != "")
                .group_by(EnvelopeRow.group)
            )
            result = await session.execute(stmt)
            return {row[0]: row[1] for row in result.all()}

    async def reset_processing_to_pending(self) -> int:
        """Reset all PROCESSING envelopes back to PENDING.

        Used at daemon startup to recover envelopes that were mid-processing
        when the previous daemon instance was killed.
        """
        async with self._session() as session:
            result = await session.execute(
                text("UPDATE envelopes SET status = 'pending' WHERE status = 'processing'")
            )
            await session.commit()
            count = result.rowcount
            if count:
                logger.info("Reset %d stuck PROCESSING envelopes to PENDING", count)
            return count

    async def save_adaptor_state(self, adaptor: str, key: str, value: str) -> None:
        """Persist a key-value pair for an adaptor (cursors, etags, etc.)."""
        async with self._session() as session:
            existing = await session.get(AdaptorStateRow, (adaptor, key))
            if existing is None:
                existing = AdaptorStateRow(adaptor=adaptor, key=key)
            existing.value = value
            session.add(existing)
            await session.commit()

    async def get_adaptor_state(self, adaptor: str, key: str) -> str | None:
        """Retrieve a stored value for an adaptor."""
        async with self._session() as session:
            row = await session.get(AdaptorStateRow, (adaptor, key))
            return row.value if row else None

    # --- Event CRUD ---

    async def create_event(self, event: Event) -> Event:
        """Insert a new tracked event."""
        async with self._session() as session:
            row = _event_to_row(event)
            session.add(row)
            await session.commit()
            return event

    async def get_event(self, event_id: str) -> Event | None:
        """Retrieve a single event by ID."""
        async with self._session() as session:
            row = await session.get(EventRow, event_id)
            if row is None:
                return None
            return _row_to_event(row)

    async def get_event_by_source_id(self, source_id: str) -> Event | None:
        """Retrieve an event by its source_id."""
        async with self._session() as session:
            stmt = select(EventRow).where(EventRow.source_id == source_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return _row_to_event(row) if row else None

    async def list_events(
        self,
        status: str | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """List events with optional filters, newest first."""
        async with self._session() as session:
            stmt = select(EventRow).order_by(EventRow.updated_at.desc())
            if status is not None:
                stmt = stmt.where(EventRow.status == status)
            if source is not None:
                stmt = stmt.where(EventRow.source == source)
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [_row_to_event(r) for r in rows]

    async def resolve_event(self, event_id: str) -> None:
        """Mark an event as resolved."""
        async with self._session() as session:
            row = await session.get(EventRow, event_id)
            if row is None:
                return
            row.status = "resolved"
            row.updated_at = datetime.utcnow()
            await session.commit()

    async def append_updates(self, source_id: str, new_updates: list[dict]) -> None:
        """Append updates to an event and bump updated_at."""
        async with self._session() as session:
            stmt = select(EventRow).where(EventRow.source_id == source_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return
            existing = json.loads(row.updates) if row.updates else []
            existing.extend(new_updates)
            row.updates = json.dumps(existing)
            row.updated_at = datetime.utcnow()
            await session.commit()

    async def update_event_summary(self, event_id: str, summary: str) -> None:
        """Update the agent summary for an event."""
        async with self._session() as session:
            row = await session.get(EventRow, event_id)
            if row is None:
                return
            row.agent_summary = summary
            row.updated_at = datetime.utcnow()
            await session.commit()

    async def update_event_metadata(self, event_id: str, metadata: dict) -> None:
        """Replace event metadata."""
        async with self._session() as session:
            row = await session.get(EventRow, event_id)
            if row is None:
                return
            row.metadata_ = json.dumps(metadata)
            row.updated_at = datetime.utcnow()
            await session.commit()

    async def save_event(self, event: Event) -> None:
        """Upsert an event (insert or update by ID)."""
        async with self._session() as session:
            existing = await session.get(EventRow, event.id)
            row = _event_to_row(event, existing)
            session.add(row)
            await session.commit()
