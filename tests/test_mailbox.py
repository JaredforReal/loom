"""Tests for Mailbox.save_and_transition — agent fields survive status changes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loom.core.envelope import Envelope, EnvelopeStatus
from loom.core.eventbus import EventBus
from loom.core.mailbox import Mailbox
from loom.state.store import Store


@pytest.fixture
async def mailbox(db_path: Path) -> Mailbox:
    store = Store(db_path=db_path)
    await store.init()
    bus = EventBus()
    mb = Mailbox(store, bus)
    yield mb
    await store.close()


class TestSaveAndTransition:
    async def test_agent_fields_persisted_on_done(self, mailbox: Mailbox) -> None:
        env = Envelope(source="github", title="test", body="body")
        await mailbox.receive(env)

        env.agent_summary = "Summarized: this is important"
        env.proposed_action = {"auto_approved": True, "result": "ok"}
        await mailbox.save_and_transition(env, EnvelopeStatus.DONE)

        loaded = await mailbox._store.get_envelope(env.id)
        assert loaded is not None
        assert loaded.status == EnvelopeStatus.DONE
        assert loaded.agent_summary == "Summarized: this is important"
        assert loaded.proposed_action == {"auto_approved": True, "result": "ok"}

    async def test_agent_log_persisted_on_in_review(self, mailbox: Mailbox) -> None:
        env = Envelope(source="gmail", title="test", body="body")
        await mailbox.receive(env)

        env.agent_summary = "Email needs your review"
        env.agent_log = [
            {
                "step": "triage",
                "input": "read email",
                "output": "urgent",
                "timestamp": "2024-01-01T00:00:00",
            }
        ]
        await mailbox.save_and_transition(env, EnvelopeStatus.IN_REVIEW)

        loaded = await mailbox._store.get_envelope(env.id)
        assert loaded is not None
        assert loaded.status == EnvelopeStatus.IN_REVIEW
        assert loaded.agent_summary == "Email needs your review"
        assert len(loaded.agent_log) == 1
        assert loaded.agent_log[0]["step"] == "triage"

    async def test_error_summary_persisted_on_failed(self, mailbox: Mailbox) -> None:
        env = Envelope(source="rss", title="test", body="body")
        await mailbox.receive(env)

        env.agent_summary = "Session failed: timeout"
        await mailbox.save_and_transition(env, EnvelopeStatus.FAILED)

        loaded = await mailbox._store.get_envelope(env.id)
        assert loaded is not None
        assert loaded.status == EnvelopeStatus.FAILED
        assert loaded.agent_summary == "Session failed: timeout"

    async def test_event_published(self, mailbox: Mailbox) -> None:
        env = Envelope(source="github", title="test", body="body")
        await mailbox.receive(env)

        events: list = []

        async def capture(_event: str, data: object) -> None:
            events.append(data)

        mailbox._bus.subscribe("envelope_status_changed", capture)

        env.agent_summary = "summary"
        await mailbox.save_and_transition(env, EnvelopeStatus.DONE)

        # Allow the asyncio task spawned by publish to run
        await asyncio.sleep(0)

        assert len(events) == 1
        assert events[0].status == EnvelopeStatus.DONE
        assert events[0].agent_summary == "summary"

    async def test_update_status_discards_mutations(self, mailbox: Mailbox) -> None:
        env = Envelope(source="github", title="test", body="body")
        await mailbox.receive(env)

        env.agent_summary = "This should be lost"
        await mailbox.update_status(env.id, EnvelopeStatus.DONE)

        loaded = await mailbox._store.get_envelope(env.id)
        assert loaded is not None
        assert loaded.agent_summary == ""
