"""arXiv Search API adaptor — polls for new papers matching configured queries.

Strategy:
  - Use the ``arxiv`` Python package (wraps the arXiv Search API with built-in
    3-second rate limiting).
  - Each ``ArxivSourceConfig`` defines a query — either an explicit API query
    string or one assembled from ``categories`` + ``keywords``.
  - Poll with ``submittedDate`` range filtering for incremental fetches.
  - Deduplicate by arXiv short ID in memory.
  - Read-only adaptor — ``execute_action`` is a no-op.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import arxiv  # type: ignore[import-untyped]

from loom.adaptor.base import BaseAdaptor
from loom.core.envelope import Envelope, EnvelopeStatus

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 43200  # 12 hours (arXiv updates daily at midnight EST)
DEFAULT_MAX_RESULTS = 50


@dataclass
class ArxivSourceConfig:
    """Configuration for one arXiv search subscription."""

    query: str = ""
    categories: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    poll_interval: int = DEFAULT_POLL_INTERVAL
    max_results: int = DEFAULT_MAX_RESULTS
    group: str = ""

    def build_query(self) -> str:
        """Return the effective query string."""
        if self.query:
            return self.query
        parts: list[str] = []
        if self.categories:
            cat_part = " OR ".join(f"cat:{c}" for c in self.categories)
            parts.append(f"({cat_part})")
        if self.keywords:
            kw_part = " OR ".join(f'ti:"{k}"' for k in self.keywords)
            parts.append(f"({kw_part})")
        return " AND ".join(parts) if parts else ""


def _poll_source_sync(
    query: str, date_filter: str, max_results: int, proxy: str | None = None
) -> list[Any]:
    """Run a synchronous arxiv search and return results."""
    full_query = f"{query} AND {date_filter}" if query else date_filter
    client = arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=3)
    if proxy:
        client._session.proxies = {"http": proxy, "https": proxy}
    search = arxiv.Search(
        query=full_query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )
    return list(client.results(search))


class ArxivAdaptor(BaseAdaptor):
    """Polls arXiv for new papers and emits Envelopes through ``_emit``."""

    name = "arxiv"

    def __init__(self, proxy: str | None = None) -> None:
        self._proxy = proxy
        self._sources: dict[str, ArxivSourceConfig] = {}
        self._seen_ids: set[str] = set()
        self._last_polled: dict[str, datetime] = {}
        self._running = False
        self._poll_task: Any | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def add_source(self, config: ArxivSourceConfig) -> None:
        key = config.build_query()
        self._sources[key] = config
        self._last_polled[key] = datetime.now(UTC) - timedelta(days=7)
        logger.info("arxiv source added: %s (poll every %ds)", key[:80], config.poll_interval)

    def remove_source(self, key: str) -> None:
        self._sources.pop(key, None)
        self._last_polled.pop(key, None)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self._sources:
            logger.warning("No arxiv sources configured — adaptor idle")
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("arxiv adaptor started — monitoring %d query/queries", len(self._sources))

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None
        logger.info("arxiv adaptor stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        while self._running:
            for key, config in list(self._sources.items()):
                if not self._running:
                    break
                try:
                    await self._poll_source(key, config)
                except Exception as exc:
                    logger.error("Error polling arxiv '%s': %s", key[:60], exc)

            min_interval = min(
                (c.poll_interval for c in self._sources.values()),
                default=DEFAULT_POLL_INTERVAL,
            )
            await asyncio.sleep(min_interval)

    async def _poll_source(self, key: str, config: ArxivSourceConfig) -> None:
        since = self._last_polled.get(key)
        if since is None:
            since = datetime.now(UTC) - timedelta(hours=24)
        now = datetime.now(UTC)

        since_str = since.strftime("%Y%m%d%H%M")
        now_str = now.strftime("%Y%m%d%H%M")
        date_filter = f"submittedDate:[{since_str} TO {now_str}]"

        try:
            results = await asyncio.wait_for(
                asyncio.to_thread(
                    _poll_source_sync, key, date_filter, config.max_results, self._proxy
                ),
                timeout=60,
            )
        except TimeoutError:
            logger.error("arxiv API timeout for '%s' (60s)", key[:60])
            return
        except Exception as exc:
            logger.error("arxiv API error for '%s': %s", key[:60], exc)
            return

        for result in results:
            envelope = await self.normalize(result)
            envelope.group = config.group

            if envelope.source_id in self._seen_ids:
                continue
            self._seen_ids.add(envelope.source_id)

            await self._emit(envelope)
            logger.info(
                "New arxiv envelope: %s — %s",
                envelope.source_id,
                envelope.title[:60],
            )

        self._last_polled[key] = now

    # ------------------------------------------------------------------
    # Normalize
    # ------------------------------------------------------------------

    async def normalize(self, raw_event: Any) -> Envelope:
        """Convert an ``arxiv.Result`` into an Envelope."""
        result = raw_event

        source_id = result.get_short_id()
        title = result.title.replace("\n", " ").strip()
        body = result.summary.replace("\n", " ").strip()
        received_at = result.published if result.published else datetime.now(UTC)
        labels = list(result.categories) if result.categories else []

        authors = [a.name for a in result.authors] if result.authors else []
        metadata: dict[str, Any] = {
            "entry_id": result.entry_id,
            "authors": authors,
            "primary_category": result.primary_category,
            "pdf_url": result.pdf_url,
            "doi": result.doi,
            "journal_ref": result.journal_ref,
            "comment": result.comment,
            "published": result.published.isoformat() if result.published else None,
            "updated": result.updated.isoformat() if result.updated else None,
        }

        return Envelope(
            source=self.name,
            source_id=source_id,
            title=title,
            body=body,
            received_at=received_at,
            status=EnvelopeStatus.PENDING,
            priority=1,
            labels=labels,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Execute actions (arxiv is read-only)
    # ------------------------------------------------------------------

    async def execute_action(self, envelope: Envelope, action: dict) -> None:
        logger.debug("arxiv adaptor received action request (read-only, ignoring): %s", action)

    def export_seen(self) -> list[str]:
        return list(self._seen_ids)

    def restore_seen(self, entries: list[str]) -> None:
        self._seen_ids.update(e for e in entries if isinstance(e, str))
