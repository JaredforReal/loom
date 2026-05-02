"""RSS/Atom feed adaptor — HTTP polling with feedparser normalization.

Strategy:
  - Poll RSS/Atom feeds on a configurable interval using ``httpx``.
  - Parse responses with ``feedparser`` for robust handling of RSS 2.0,
    Atom, RDF, and edge-case feeds.
  - Deduplicate by entry ``id`` (GUID) or ``link`` — skip items already
    in the mailbox.
  - Support conditional requests via ``ETag`` / ``Last-Modified`` to save
    bandwidth.
  - Read-only adaptor — ``execute_action`` is a no-op.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser  # type: ignore[import-untyped]
import httpx

from loom.adaptor.base import BaseAdaptor
from loom.core.envelope import Envelope, EnvelopeStatus

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 300  # 5 minutes


@dataclass
class RSSSourceConfig:
    """Configuration for one RSS/Atom feed subscription."""

    url: str
    poll_interval: int = DEFAULT_POLL_INTERVAL
    title_filter: list[str] = field(default_factory=list)  # keywords to include


class RSSAdaptor(BaseAdaptor):
    """Polls RSS/Atom feeds and emits Envelopes through ``_emit``."""

    name = "rss"

    def __init__(self, proxy: str | None = None) -> None:
        self._proxy = proxy
        self._sources: dict[str, RSSSourceConfig] = {}  # key = feed URL
        self._etags: dict[str, str] = {}
        self._modified: dict[str, str] = {}
        self._seen_ids: set[str] = set()
        self._running = False
        self._client: httpx.AsyncClient | None = None
        self._poll_task: Any | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def add_source(self, config: RSSSourceConfig) -> None:
        """Add an RSS/Atom feed to monitor."""
        self._sources[config.url] = config
        logger.info("RSS source added: %s (poll every %ds)", config.url, config.poll_interval)

    def remove_source(self, url: str) -> None:
        self._sources.pop(url, None)
        self._etags.pop(url, None)
        self._modified.pop(url, None)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self._sources:
            logger.warning("No RSS sources configured — adaptor idle")
            return

        self._client = httpx.AsyncClient(
            timeout=30.0,
            proxy=self._proxy,
            follow_redirects=True,
            headers={"User-Agent": "Loom/0.1 (RSS Reader)"},
        )
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("RSS adaptor started — monitoring %d feed(s)", len(self._sources))

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("RSS adaptor stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Main polling loop — iterates over all feeds with per-source intervals."""
        while self._running:
            for url, config in list(self._sources.items()):
                if not self._running:
                    break
                try:
                    await self._poll_feed(url, config)
                except Exception as exc:
                    logger.error("Error polling %s: %s", url, exc)

            min_interval = min(
                (c.poll_interval for c in self._sources.values()),
                default=DEFAULT_POLL_INTERVAL,
            )
            await asyncio.sleep(min_interval)

    async def _poll_feed(self, url: str, config: RSSSourceConfig) -> None:
        """Poll a single feed for new entries."""
        assert self._client is not None

        headers: dict[str, str] = {}
        if url in self._etags:
            headers["If-None-Match"] = self._etags[url]
        if url in self._modified:
            headers["If-Modified-Since"] = self._modified[url]

        resp = await self._client.get(url, headers=headers)

        # 304 Not Modified — nothing new
        if resp.status_code == 304:
            return

        resp.raise_for_status()

        # Save conditional request headers for next poll
        if etag := resp.headers.get("ETag"):
            self._etags[url] = etag
        if lm := resp.headers.get("Last-Modified"):
            self._modified[url] = lm

        # Parse with feedparser from raw bytes
        parsed = feedparser.parse(resp.content)

        bozo = getattr(parsed, "bozo", False)
        bozo_exc = getattr(parsed, "bozo_exception", None)
        if bozo and bozo_exc and not getattr(parsed, "entries", None):
            logger.warning("Feed parse error for %s: %s", url, bozo_exc)
            return

        feed_title = getattr(parsed.feed, "title", "")

        for entry in parsed.entries:
            envelope = await self.normalize(
                {
                    "entry": entry,
                    "feed_url": url,
                    "feed_title": feed_title,
                }
            )

            # Dedup: skip if we've already processed this source_id
            if envelope.source_id in self._seen_ids:
                continue
            self._seen_ids.add(envelope.source_id)

            # Filter by title keywords if configured
            if config.title_filter:
                if not any(kw.lower() in envelope.title.lower() for kw in config.title_filter):
                    continue

            await self._emit(envelope)
            logger.info(
                "New RSS envelope: %s — %s",
                envelope.source_id,
                envelope.title[:60],
            )

    # ------------------------------------------------------------------
    # Normalize
    # ------------------------------------------------------------------

    async def normalize(self, raw_event: Any) -> Envelope:
        """Convert a feedparser entry into an Envelope."""
        entry = raw_event["entry"]
        feed_url = raw_event["feed_url"]
        feed_title = raw_event.get("feed_title", "")

        # Unique ID: prefer guid/id, fall back to link
        source_id = getattr(entry, "id", "") or getattr(entry, "link", "") or ""

        title = getattr(entry, "title", "Untitled")

        # Body: prefer summary/detail, fall back to description
        body = ""
        if hasattr(entry, "summary"):
            body = entry.summary
        elif hasattr(entry, "description"):
            body = entry.description

        # Parse published/updated time
        received_at = datetime.utcnow()
        for time_field in ("published_parsed", "updated_parsed"):
            time_tuple = getattr(entry, time_field, None)
            if time_tuple:
                try:
                    received_at = datetime(*time_tuple[:6])
                except (TypeError, ValueError):
                    pass
                break
        # Fallback: try RFC 2822 string
        if received_at == datetime.utcnow():
            for time_str_field in ("published", "updated"):
                raw = getattr(entry, time_str_field, "")
                if raw:
                    try:
                        received_at = parsedate_to_datetime(raw)
                    except (TypeError, ValueError):
                        pass
                    break

        link = getattr(entry, "link", "")
        author = getattr(entry, "author", "")
        tags = [t.get("term", "") for t in getattr(entry, "tags", []) if t.get("term")]

        # Build metadata
        metadata: dict[str, Any] = {
            "feed_url": feed_url,
            "feed_title": feed_title,
            "link": link,
            "author": author,
            "tags": tags,
        }
        if hasattr(entry, "enclosures") and entry.enclosures:
            metadata["enclosures"] = [
                {"url": e.get("href", ""), "type": e.get("type", ""), "length": e.get("length", "")}
                for e in entry.enclosures
            ]

        return Envelope(
            source=self.name,
            source_id=source_id,
            title=title,
            body=body,
            received_at=received_at,
            status=EnvelopeStatus.PENDING,
            priority=1,
            labels=tags,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Execute actions (RSS is read-only)
    # ------------------------------------------------------------------

    async def execute_action(self, envelope: Envelope, action: dict) -> None:
        """RSS is a read-only source — no actions to execute."""
        logger.debug("RSS adaptor received action request (read-only, ignoring): %s", action)
