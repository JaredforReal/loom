"""Tests for loom.orchestrator.session on_complete callback."""

from __future__ import annotations

from pathlib import Path

from loom.orchestrator.session import Session, SessionManager, SessionStatus


class TestOnCompleteCallback:
    async def test_callback_called_on_session_failure(self, tmp_path: Path) -> None:
        completed: list[Session] = []

        async def on_complete(session: Session) -> None:
            completed.append(session)

        mgr = SessionManager(prompt_dir=tmp_path, on_complete=on_complete)

        session = Session(envelope_id="env-1", status=SessionStatus.RUNNING)
        mgr._sessions[session.id] = session

        # Call _run_session with no client — triggers FAILED path
        await mgr._run_session(session, "test prompt")

        assert session.status == SessionStatus.FAILED
        assert len(completed) == 1
        assert completed[0].id == session.id
        assert completed[0].envelope_id == "env-1"

    async def test_no_callback_when_none(self, tmp_path: Path) -> None:
        mgr = SessionManager(prompt_dir=tmp_path)
        session = Session(envelope_id="env-1", status=SessionStatus.RUNNING)
        mgr._sessions[session.id] = session

        # Should not raise
        await mgr._run_session(session, "test prompt")
        assert session.status == SessionStatus.FAILED

    async def test_callback_exception_does_not_propagate(self, tmp_path: Path) -> None:
        async def bad_callback(session: Session) -> None:
            raise RuntimeError("callback boom")

        mgr = SessionManager(prompt_dir=tmp_path, on_complete=bad_callback)
        session = Session(envelope_id="env-1", status=SessionStatus.RUNNING)
        mgr._sessions[session.id] = session

        # Should not raise despite callback failure
        await mgr._run_session(session, "test prompt")
        assert session.status == SessionStatus.FAILED
