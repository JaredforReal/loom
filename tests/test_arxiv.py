"""Tests for loom.adaptor.arxiv — ArxivSourceConfig and ArxivAdaptor."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from loom.adaptor.arxiv import ArxivAdaptor, ArxivSourceConfig, _poll_source_sync
from loom.core.envelope import EnvelopeStatus

# ---------------------------------------------------------------------------
# ArxivSourceConfig.build_query
# ---------------------------------------------------------------------------


class TestBuildQuery:
    def test_explicit_query(self) -> None:
        cfg = ArxivSourceConfig(query="cat:cs.AI AND ti:agent")
        assert cfg.build_query() == "cat:cs.AI AND ti:agent"

    def test_categories_only(self) -> None:
        cfg = ArxivSourceConfig(categories=["cs.AI", "cs.CL"])
        q = cfg.build_query()
        assert "cat:cs.AI" in q
        assert "cat:cs.CL" in q
        assert " OR " in q

    def test_keywords_only(self) -> None:
        cfg = ArxivSourceConfig(keywords=["LLM", "agent"])
        q = cfg.build_query()
        assert 'ti:"LLM"' in q
        assert 'ti:"agent"' in q
        assert " OR " in q

    def test_categories_and_keywords(self) -> None:
        cfg = ArxivSourceConfig(categories=["cs.AI"], keywords=["agent"])
        q = cfg.build_query()
        assert "cat:cs.AI" in q
        assert 'ti:"agent"' in q
        assert " AND " in q

    def test_empty_fallback(self) -> None:
        cfg = ArxivSourceConfig()
        assert cfg.build_query() == ""


# ---------------------------------------------------------------------------
# ArxivAdaptor.normalize
# ---------------------------------------------------------------------------


def _mock_result(
    entry_id: str = "http://arxiv.org/abs/2505.01234v1",
    title: str = "A Great Paper\nOn AI",
    summary: str = "This is the abstract.\nWith newlines.",
    published: datetime | None = None,
    categories: list[str] | None = None,
    authors: list[str] | None = None,
    pdf_url: str = "https://arxiv.org/pdf/2505.01234v1",
    doi: str | None = None,
) -> MagicMock:
    result = MagicMock()
    result.entry_id = entry_id
    result.title = title
    result.summary = summary
    result.published = published or datetime(2025, 5, 1, 12, 0, 0, tzinfo=UTC)
    result.updated = result.published
    result.primary_category = "cs.AI"
    result.categories = categories or ["cs.AI", "cs.LG"]
    result.authors = [MagicMock(name=n) for n in (authors or ["Alice", "Bob"])]
    for a, name in zip(result.authors, authors or ["Alice", "Bob"]):
        a.name = name
    result.pdf_url = pdf_url
    result.doi = doi
    result.journal_ref = None
    result.comment = "10 pages"
    result.get_short_id.return_value = "2505.01234v1"
    return result


class TestNormalize:
    @pytest.mark.asyncio
    async def test_basic_mapping(self) -> None:
        adaptor = ArxivAdaptor()
        result = _mock_result()
        envelope = await adaptor.normalize(result)

        assert envelope.source == "arxiv"
        assert envelope.source_id == "2505.01234v1"
        assert envelope.title == "A Great Paper On AI"
        assert "abstract." in envelope.body
        assert "\n" not in envelope.title
        assert "\n" not in envelope.body
        assert envelope.status == EnvelopeStatus.PENDING
        assert envelope.priority == 1

    @pytest.mark.asyncio
    async def test_labels_from_categories(self) -> None:
        adaptor = ArxivAdaptor()
        result = _mock_result(categories=["cs.AI", "cs.CL"])
        envelope = await adaptor.normalize(result)
        assert envelope.labels == ["cs.AI", "cs.CL"]

    @pytest.mark.asyncio
    async def test_metadata_fields(self) -> None:
        adaptor = ArxivAdaptor()
        result = _mock_result(authors=["Alice"], doi="10.1234/test")
        envelope = await adaptor.normalize(result)
        assert envelope.metadata["authors"] == ["Alice"]
        assert envelope.metadata["doi"] == "10.1234/test"
        assert envelope.metadata["pdf_url"] is not None
        assert envelope.metadata["entry_id"] is not None
        assert envelope.metadata["primary_category"] == "cs.AI"


# ---------------------------------------------------------------------------
# ArxivAdaptor lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_no_sources(self) -> None:
        adaptor = ArxivAdaptor()
        await adaptor.start()
        assert not adaptor.is_running

    @pytest.mark.asyncio
    async def test_start_stop_with_source(self) -> None:
        adaptor = ArxivAdaptor()
        adaptor.set_callback(AsyncMock())
        adaptor.add_source(ArxivSourceConfig(categories=["cs.AI"]))
        await adaptor.start()
        assert adaptor.is_running
        assert adaptor._poll_task is not None

        await adaptor.stop()
        assert not adaptor.is_running
        assert adaptor._poll_task is None

    @pytest.mark.asyncio
    async def test_add_source_initializes_last_polled(self) -> None:
        adaptor = ArxivAdaptor()
        adaptor.add_source(ArxivSourceConfig(categories=["cs.AI"]))
        key = list(adaptor._last_polled.keys())[0]
        delta = datetime.now(UTC) - adaptor._last_polled[key]
        assert 6 * 86400 < delta.total_seconds() < 8 * 86400


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDedup:
    @pytest.mark.asyncio
    async def test_seen_ids_skipped(self) -> None:
        adaptor = ArxivAdaptor()
        callback = AsyncMock()
        adaptor.set_callback(callback)

        adaptor.add_source(ArxivSourceConfig(categories=["cs.AI"]))
        key = list(adaptor._sources.keys())[0]

        # Mark as already seen
        adaptor._seen_ids.add("2505.01234v1")

        result = _mock_result()
        with patch("loom.adaptor.arxiv._poll_source_sync", return_value=[result]):
            await adaptor._poll_source(key, adaptor._sources[key])

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_new_id_emitted(self) -> None:
        adaptor = ArxivAdaptor()
        callback = AsyncMock()
        adaptor.set_callback(callback)

        adaptor.add_source(ArxivSourceConfig(categories=["cs.AI"]))
        key = list(adaptor._sources.keys())[0]

        result = _mock_result()
        with patch("loom.adaptor.arxiv._poll_source_sync", return_value=[result]):
            await adaptor._poll_source(key, adaptor._sources[key])

        callback.assert_called_once()
        envelope = callback.call_args[0][0]
        assert envelope.source_id == "2505.01234v1"
        assert "2505.01234v1" in adaptor._seen_ids


# ---------------------------------------------------------------------------
# _poll_source_sync helper
# ---------------------------------------------------------------------------


class TestPollSourceSync:
    def test_builds_correct_query(self) -> None:
        with patch("loom.adaptor.arxiv.arxiv") as mock_arxiv:
            mock_client = MagicMock()
            mock_arxiv.Client.return_value = mock_client
            mock_client.results.return_value = iter([])
            mock_arxiv.SortCriterion.SubmittedDate = "submittedDate"
            mock_arxiv.SortOrder.Descending = "descending"

            _poll_source_sync("cat:cs.AI", "submittedDate:[202501010000+TO+202505020000]", 20)

            mock_arxiv.Client.assert_called_once_with(
                page_size=100, delay_seconds=3.0, num_retries=3
            )
            search_arg = mock_arxiv.Search.call_args
            assert "cat:cs.AI" in search_arg.kwargs["query"]
            assert "submittedDate:" in search_arg.kwargs["query"]
