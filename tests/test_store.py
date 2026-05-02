"""Tests for loom.state.store module."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from loom.core.envelope import Envelope, EnvelopeStatus
from loom.state.store import Store


def _make_envelope(
    source: str = "github",
    source_id: str = "acme/app#1",
    title: str = "Test issue",
    status: EnvelopeStatus = EnvelopeStatus.PENDING,
    priority: int = 1,
    labels: list[str] | None = None,
    metadata: dict | None = None,
    agent_summary: str = "",
    agent_log: list[dict] | None = None,
    proposed_action: dict | None = None,
) -> Envelope:
    return Envelope(
        source=source,
        source_id=source_id,
        title=title,
        body="Test body",
        status=status,
        priority=priority,
        labels=labels or [],
        metadata=metadata or {},
        agent_summary=agent_summary,
        agent_log=agent_log or [],
        proposed_action=proposed_action,
    )


@pytest.fixture
async def store(db_path: Path) -> Store:
    """Provide an initialized Store (async, same event loop as tests)."""
    s = Store(db_path=db_path)
    await s.init()
    yield s
    await s.close()


class TestStoreInit:
    async def test_init_creates_db_file(self, db_path: Path) -> None:
        s = Store(db_path=db_path)
        await s.init()
        assert db_path.exists()
        await s.close()

    async def test_init_creates_parent_dir(self, tmp_path: Path) -> None:
        db_path = tmp_path / "deep" / "nested" / "test.db"
        s = Store(db_path=db_path)
        await s.init()
        assert db_path.exists()
        await s.close()

    async def test_init_idempotent(self, store: Store) -> None:
        await store.init()  # should not error


class TestSaveAndGetEnvelope:
    async def test_roundtrip(self, store: Store) -> None:
        env = _make_envelope()
        await store.save_envelope(env)
        loaded = await store.get_envelope(env.id)
        assert loaded is not None
        assert loaded.id == env.id
        assert loaded.source == "github"
        assert loaded.title == "Test issue"
        assert loaded.body == "Test body"

    async def test_status_preserved(self, store: Store) -> None:
        env = _make_envelope(status=EnvelopeStatus.WAITING_APPROVAL)
        await store.save_envelope(env)
        loaded = await store.get_envelope(env.id)
        assert loaded is not None
        assert loaded.status == EnvelopeStatus.WAITING_APPROVAL

    async def test_priority_preserved(self, store: Store) -> None:
        env = _make_envelope(priority=3)
        await store.save_envelope(env)
        loaded = await store.get_envelope(env.id)
        assert loaded is not None
        assert loaded.priority == 3

    async def test_labels_roundtrip(self, store: Store) -> None:
        env = _make_envelope(labels=["bug", "P0", "help-wanted"])
        await store.save_envelope(env)
        loaded = await store.get_envelope(env.id)
        assert loaded is not None
        assert loaded.labels == ["bug", "P0", "help-wanted"]

    async def test_metadata_roundtrip(self, store: Store) -> None:
        env = _make_envelope(metadata={"repo": "acme/app", "number": 42, "kind": "issue"})
        await store.save_envelope(env)
        loaded = await store.get_envelope(env.id)
        assert loaded is not None
        assert loaded.metadata["repo"] == "acme/app"
        assert loaded.metadata["number"] == 42

    async def test_agent_log_roundtrip(self, store: Store) -> None:
        log = [
            {"step": "triage", "input": "read issue", "output": "classified", "ts": "2024-01-01"}
        ]
        env = _make_envelope(agent_log=log)
        await store.save_envelope(env)
        loaded = await store.get_envelope(env.id)
        assert loaded is not None
        assert len(loaded.agent_log) == 1
        assert loaded.agent_log[0]["step"] == "triage"

    async def test_proposed_action_roundtrip(self, store: Store) -> None:
        action = {"type": "comment", "body": "triaged"}
        env = _make_envelope(proposed_action=action)
        await store.save_envelope(env)
        loaded = await store.get_envelope(env.id)
        assert loaded is not None
        assert loaded.proposed_action["type"] == "comment"

    async def test_proposed_action_none_roundtrip(self, store: Store) -> None:
        env = _make_envelope(proposed_action=None)
        await store.save_envelope(env)
        loaded = await store.get_envelope(env.id)
        assert loaded is not None
        assert loaded.proposed_action is None

    async def test_upsert_on_same_id(self, store: Store) -> None:
        env = _make_envelope(title="v1")
        await store.save_envelope(env)

        env.title = "v2"
        env.status = EnvelopeStatus.DONE
        await store.save_envelope(env)

        loaded = await store.get_envelope(env.id)
        assert loaded is not None
        assert loaded.title == "v2"
        assert loaded.status == EnvelopeStatus.DONE

    async def test_get_nonexistent_returns_none(self, store: Store) -> None:
        result = await store.get_envelope("does-not-exist")
        assert result is None


class TestQueryEnvelopes:
    async def test_returns_newest_first(self, store: Store) -> None:
        env1 = _make_envelope(source_id="old", title="First")
        env1.received_at = datetime(2024, 1, 1)
        env2 = _make_envelope(source_id="new", title="Second")
        env2.received_at = datetime(2024, 1, 2)
        await store.save_envelope(env1)
        await store.save_envelope(env2)
        results = await store.query_envelopes()
        assert len(results) == 2
        assert results[0].title == "Second"

    async def test_filter_by_source(self, store: Store) -> None:
        await store.save_envelope(_make_envelope(source="github"))
        await store.save_envelope(_make_envelope(source="gmail"))
        results = await store.query_envelopes(source="github")
        assert len(results) == 1
        assert results[0].source == "github"

    async def test_filter_by_status(self, store: Store) -> None:
        await store.save_envelope(_make_envelope(status=EnvelopeStatus.PENDING))
        await store.save_envelope(_make_envelope(status=EnvelopeStatus.DONE))
        results = await store.query_envelopes(status=EnvelopeStatus.DONE)
        assert len(results) == 1
        assert results[0].status == EnvelopeStatus.DONE

    async def test_respects_limit(self, store: Store) -> None:
        for i in range(10):
            await store.save_envelope(_make_envelope(source_id=f"#{i}"))
        results = await store.query_envelopes(limit=3)
        assert len(results) == 3

    async def test_combined_filters(self, store: Store) -> None:
        await store.save_envelope(_make_envelope(source="github", status=EnvelopeStatus.PENDING))
        await store.save_envelope(_make_envelope(source="github", status=EnvelopeStatus.DONE))
        await store.save_envelope(_make_envelope(source="gmail", status=EnvelopeStatus.PENDING))
        results = await store.query_envelopes(source="github", status=EnvelopeStatus.PENDING)
        assert len(results) == 1

    async def test_empty_result(self, store: Store) -> None:
        results = await store.query_envelopes(source="nonexistent")
        assert results == []


class TestGetUnreadCounts:
    async def test_counts_pending_and_waiting(self, store: Store) -> None:
        await store.save_envelope(_make_envelope(source="github", status=EnvelopeStatus.PENDING))
        await store.save_envelope(
            _make_envelope(source="github", status=EnvelopeStatus.WAITING_APPROVAL)
        )
        await store.save_envelope(_make_envelope(source="github", status=EnvelopeStatus.DONE))
        counts = await store.get_unread_counts()
        assert counts.get("github") == 2

    async def test_grouped_by_source(self, store: Store) -> None:
        await store.save_envelope(_make_envelope(source="github", status=EnvelopeStatus.PENDING))
        await store.save_envelope(_make_envelope(source="gmail", status=EnvelopeStatus.PENDING))
        counts = await store.get_unread_counts()
        assert counts["github"] == 1
        assert counts["gmail"] == 1

    async def test_filter_by_source(self, store: Store) -> None:
        await store.save_envelope(_make_envelope(source="github", status=EnvelopeStatus.PENDING))
        await store.save_envelope(_make_envelope(source="gmail", status=EnvelopeStatus.PENDING))
        counts = await store.get_unread_counts(source="github")
        assert "gmail" not in counts
        assert counts["github"] == 1

    async def test_empty_store(self, store: Store) -> None:
        counts = await store.get_unread_counts()
        assert counts == {}


class TestResetProcessing:
    async def test_resets_processing_to_pending(self, store: Store) -> None:
        env1 = _make_envelope(source_id="#1", status=EnvelopeStatus.PROCESSING)
        env2 = _make_envelope(source_id="#2", status=EnvelopeStatus.PROCESSING)
        env3 = _make_envelope(source_id="#3", status=EnvelopeStatus.DONE)
        await store.save_envelope(env1)
        await store.save_envelope(env2)
        await store.save_envelope(env3)

        count = await store.reset_processing_to_pending()
        assert count == 2

        loaded1 = await store.get_envelope(env1.id)
        assert loaded1.status == EnvelopeStatus.PENDING
        loaded2 = await store.get_envelope(env2.id)
        assert loaded2.status == EnvelopeStatus.PENDING
        loaded3 = await store.get_envelope(env3.id)
        assert loaded3.status == EnvelopeStatus.DONE

    async def test_no_processing_returns_zero(self, store: Store) -> None:
        await store.save_envelope(_make_envelope(status=EnvelopeStatus.PENDING))
        count = await store.reset_processing_to_pending()
        assert count == 0

    async def test_empty_store_returns_zero(self, store: Store) -> None:
        count = await store.reset_processing_to_pending()
        assert count == 0


class TestAdaptorState:
    async def test_save_and_get(self, store: Store) -> None:
        await store.save_adaptor_state("github", "cursor:acme/app", "2024-01-01T00:00:00Z")
        val = await store.get_adaptor_state("github", "cursor:acme/app")
        assert val == "2024-01-01T00:00:00Z"

    async def test_get_nonexistent_returns_none(self, store: Store) -> None:
        val = await store.get_adaptor_state("github", "nope")
        assert val is None

    async def test_upsert(self, store: Store) -> None:
        await store.save_adaptor_state("github", "etag:acme/app", "abc")
        await store.save_adaptor_state("github", "etag:acme/app", "def")
        val = await store.get_adaptor_state("github", "etag:acme/app")
        assert val == "def"

    async def test_separate_adaptors(self, store: Store) -> None:
        await store.save_adaptor_state("github", "key", "v1")
        await store.save_adaptor_state("gmail", "key", "v2")
        assert await store.get_adaptor_state("github", "key") == "v1"
        assert await store.get_adaptor_state("gmail", "key") == "v2"

    async def test_json_value(self, store: Store) -> None:
        data = json.dumps({"acme/app": "2024-01-01", "other/lib": "2024-01-02"})
        await store.save_adaptor_state("github", "cursors", data)
        val = await store.get_adaptor_state("github", "cursors")
        assert json.loads(val) == {"acme/app": "2024-01-01", "other/lib": "2024-01-02"}
