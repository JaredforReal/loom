"""Tests for loom.cli — smoke tests over the Store-backed commands."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loom.cli.main import cli
from loom.core.envelope import Envelope, EnvelopeStatus
from loom.state.store import Store


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """Invoke the CLI with argv and capture stdout+stderr, returning (exit_code, output)."""
    try:
        cli(argv)
        code = 0
    except SystemExit as exc:
        raw = exc.code
        code = 0 if raw is None else (int(raw) if isinstance(raw, int | str) else 1)
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def _make_envelope(
    source: str = "github",
    title: str = "Demo issue",
    status: EnvelopeStatus = EnvelopeStatus.IN_REVIEW,
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
    def test_empty(self, isolated_loom: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = _run(["inbox"], capsys)
        assert code == 0
        assert "no messages" in out

    def test_lists_envelopes(self, isolated_loom: Path, capsys: pytest.CaptureFixture[str]) -> None:
        env = _make_envelope(title="Login bug")
        asyncio.run(_seed(isolated_loom / "data" / "loom.db", [env]))
        code, out = _run(["inbox"], capsys)
        assert code == 0
        assert env.id[:8] in out
        assert "Login bug" in out

    def test_filter_by_source(
        self, isolated_loom: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        envs = [_make_envelope(source="github"), _make_envelope(source="gmail")]
        asyncio.run(_seed(isolated_loom / "data" / "loom.db", envs))
        code, out = _run(["inbox", "--source", "gmail"], capsys)
        assert code == 0
        assert envs[1].id[:8] in out
        assert envs[0].id[:8] not in out


class TestShow:
    def test_missing(self, isolated_loom: Path, capsys: pytest.CaptureFixture[str]) -> None:
        code, out = _run(["show", "abcd1234"], capsys)
        assert code == 1
        assert "no envelope matching" in out

    def test_by_prefix(self, isolated_loom: Path, capsys: pytest.CaptureFixture[str]) -> None:
        env = _make_envelope(title="Trace null deref")
        asyncio.run(_seed(isolated_loom / "data" / "loom.db", [env]))
        code, out = _run(["show", env.id[:8]], capsys)
        assert code == 0
        assert "Trace null deref" in out


# ---------------------------------------------------------------------------
# approve / reject — verify the database actually changes
# ---------------------------------------------------------------------------


class TestApprove:
    def test_marks_envelope_done(
        self, isolated_loom: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env = _make_envelope()
        db = isolated_loom / "data" / "loom.db"
        asyncio.run(_seed(db, [env]))

        code, out = _run(["approve", env.id], capsys)
        assert code == 0
        assert "Approved" in out

        assert asyncio.run(_read_status(db, env.id)) == EnvelopeStatus.DONE


class TestReject:
    def test_marks_envelope_dismissed(
        self, isolated_loom: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        env = _make_envelope()
        db = isolated_loom / "data" / "loom.db"
        asyncio.run(_seed(db, [env]))

        code, out = _run(["reject", env.id, "--reason", "spam"], capsys)
        assert code == 0
        assert "Rejected" in out
        assert "spam" in out

        assert asyncio.run(_read_status(db, env.id)) == EnvelopeStatus.DISMISSED


# ---------------------------------------------------------------------------
# status / doctor
# ---------------------------------------------------------------------------


class TestStatus:
    def test_shows_counts(self, isolated_loom: Path, capsys: pytest.CaptureFixture[str]) -> None:
        envs = [
            _make_envelope(status=EnvelopeStatus.PENDING),
            _make_envelope(status=EnvelopeStatus.IN_REVIEW),
            _make_envelope(status=EnvelopeStatus.IN_REVIEW),
        ]
        asyncio.run(_seed(isolated_loom / "data" / "loom.db", envs))
        code, out = _run(["status"], capsys)
        assert code == 0
        assert "queued 1" in out
        assert "in_review" in out


class TestDoctor:
    def test_fails_on_empty_setup(
        self, isolated_loom: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # No config, no sources, no db — doctor should exit non-zero.
        code, out = _run(["doctor"], capsys)
        assert code == 1
        assert "config.yaml" in out


# ---------------------------------------------------------------------------
# up / down
# ---------------------------------------------------------------------------


class TestDaemonUp:
    def test_up_opens_browser_when_already_running(
        self, isolated_loom: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import os

        pid_path = isolated_loom / "data" / "loom.pid"
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()))

        code, out = _run(["up"], capsys)
        assert code == 0
        assert "Opening" in out

    def test_daemon_rejects_when_already_running(
        self, isolated_loom: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import os

        pid_path = isolated_loom / "data" / "loom.pid"
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()))

        code, out = _run(["daemon"], capsys)
        assert code == 1
        assert "already running" in out


class TestDaemonDown:
    def test_down_when_not_running(
        self, isolated_loom: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = _run(["down"], capsys)
        assert code == 0
        assert "not running" in out

    def test_down_removes_stale_pid(
        self, isolated_loom: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        pid_path = isolated_loom / "data" / "loom.pid"
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text("999999999")

        code, out = _run(["down"], capsys)
        assert code == 0
        assert "not running" in out or "stale" in out
        assert not pid_path.exists()
