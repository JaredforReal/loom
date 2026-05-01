"""Tests for loom.cli — CliRunner smoke tests over the Store-backed commands."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from click.testing import CliRunner

from loom.cli.main import cli
from loom.core.envelope import Envelope, EnvelopeStatus
from loom.state.store import Store


def _make_envelope(
    source: str = "github",
    title: str = "Demo issue",
    status: EnvelopeStatus = EnvelopeStatus.WAITING_APPROVAL,
    priority: int = 2,
) -> Envelope:
    return Envelope(
        source=source,
        source_id=f"{source}#1",
        title=title,
        body="hello",
        status=status,
        priority=priority,
        labels=["bug"],
        proposed_action={"type": "comment", "body": "fix it"},
    )


async def _seed(db_path: Path, envelopes: list[Envelope]) -> None:
    store = Store(db_path=db_path)
    await store.init()
    try:
        for env in envelopes:
            await store.save_envelope(env)
    finally:
        await store.close()


async def _read_status(db_path: Path, envelope_id: str) -> EnvelopeStatus | None:
    store = Store(db_path=db_path)
    await store.init()
    try:
        env = await store.get_envelope(envelope_id)
        return env.status if env else None
    finally:
        await store.close()


@pytest.fixture
def isolated_loom(tmp_loom_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ~/.loom to a tmp dir for the duration of the test."""
    monkeypatch.setattr("loom.config.DEFAULT_LOOM_DIR", tmp_loom_dir)
    return tmp_loom_dir


# ---------------------------------------------------------------------------
# inbox / show
# ---------------------------------------------------------------------------


class TestInbox:
    def test_empty(self, isolated_loom: Path) -> None:
        result = CliRunner().invoke(cli, ["inbox"])
        assert result.exit_code == 0
        assert "no messages" in result.output

    def test_lists_envelopes(self, isolated_loom: Path) -> None:
        env = _make_envelope(title="Login bug")
        asyncio.run(_seed(isolated_loom / "data" / "loom.db", [env]))
        result = CliRunner().invoke(cli, ["inbox"])
        assert result.exit_code == 0
        assert env.id[:8] in result.output
        assert "Login bug" in result.output

    def test_filter_by_source(self, isolated_loom: Path) -> None:
        envs = [_make_envelope(source="github"), _make_envelope(source="gmail")]
        asyncio.run(_seed(isolated_loom / "data" / "loom.db", envs))
        result = CliRunner().invoke(cli, ["inbox", "--source", "gmail"])
        assert result.exit_code == 0
        assert envs[1].id[:8] in result.output
        assert envs[0].id[:8] not in result.output


class TestShow:
    def test_missing(self, isolated_loom: Path) -> None:
        result = CliRunner().invoke(cli, ["show", "abcd1234"])
        assert result.exit_code == 1
        assert "no envelope matching" in result.output

    def test_by_prefix(self, isolated_loom: Path) -> None:
        env = _make_envelope(title="Trace null deref")
        asyncio.run(_seed(isolated_loom / "data" / "loom.db", [env]))
        result = CliRunner().invoke(cli, ["show", env.id[:8]])
        assert result.exit_code == 0
        assert "Trace null deref" in result.output


# ---------------------------------------------------------------------------
# approve / reject — verify the database actually changes
# ---------------------------------------------------------------------------


class TestApprove:
    def test_marks_envelope_done(self, isolated_loom: Path) -> None:
        env = _make_envelope()
        db = isolated_loom / "data" / "loom.db"
        asyncio.run(_seed(db, [env]))

        result = CliRunner().invoke(cli, ["approve", env.id])
        assert result.exit_code == 0
        assert "Approved" in result.output

        assert asyncio.run(_read_status(db, env.id)) == EnvelopeStatus.DONE


class TestReject:
    def test_marks_envelope_dismissed(self, isolated_loom: Path) -> None:
        env = _make_envelope()
        db = isolated_loom / "data" / "loom.db"
        asyncio.run(_seed(db, [env]))

        result = CliRunner().invoke(cli, ["reject", env.id, "--reason", "spam"])
        assert result.exit_code == 0
        assert "Rejected" in result.output
        assert "spam" in result.output

        assert asyncio.run(_read_status(db, env.id)) == EnvelopeStatus.DISMISSED


# ---------------------------------------------------------------------------
# status / doctor
# ---------------------------------------------------------------------------


class TestStatus:
    def test_shows_counts(self, isolated_loom: Path) -> None:
        envs = [
            _make_envelope(status=EnvelopeStatus.PENDING),
            _make_envelope(status=EnvelopeStatus.WAITING_APPROVAL),
            _make_envelope(status=EnvelopeStatus.WAITING_APPROVAL),
        ]
        asyncio.run(_seed(isolated_loom / "data" / "loom.db", envs))
        result = CliRunner().invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "queued 1" in result.output
        assert "waiting_approval" in result.output


class TestDoctor:
    def test_fails_on_empty_setup(self, isolated_loom: Path) -> None:
        # No config, no sources, no db — doctor should exit non-zero.
        result = CliRunner().invoke(cli, ["doctor"])
        assert result.exit_code == 1
        assert "config.yaml" in result.output
