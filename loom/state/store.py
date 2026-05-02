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
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [_row_to_envelope(r) for r in rows]

    async def get_unread_counts(self, source: str | None = None) -> dict[str, int]:
        """Return {source: count} for pending/waiting_approval envelopes."""
        async with self._session() as session:
            stmt = (
                select(EnvelopeRow.source, func.count(EnvelopeRow.id))
                .where(
                    EnvelopeRow.status.in_(
                        [
                            str(EnvelopeStatus.PENDING),
                            str(EnvelopeStatus.WAITING_APPROVAL),
                        ]
                    )
                )
                .group_by(EnvelopeRow.source)
            )
            if source is not None:
                stmt = stmt.where(EnvelopeRow.source == source)
            result = await session.execute(stmt)
            return {row[0]: row[1] for row in result.all()}

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
