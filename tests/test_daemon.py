"""Tests for loom.daemon module."""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from loom.config import AgentSettings, DaemonSettings, LoomConfig, PathSettings
from loom.daemon import DaemonContext, _build_adaptors, get_context, set_context


def _make_config(tmp_path: Path, sources: list[dict] | None = None) -> LoomConfig:
    return LoomConfig(
        daemon=DaemonSettings(host="127.0.0.1", port=0),
        agent=AgentSettings(max_concurrent=2),
        sources=sources or [],
        paths=PathSettings(
            data_dir=tmp_path / "data",
            policies_dir=tmp_path / "policies",
            prompts_dir=tmp_path / "prompts",
            credentials_dir=tmp_path / "credentials",
        ),
    )


class TestDaemonContext:
    def test_get_context_raises_when_not_set(self) -> None:
        # Ensure context is cleared
        import loom.daemon

        loom.daemon._ctx = None
        with pytest.raises(RuntimeError, match="Daemon not running"):
            get_context()

    def test_set_and_get_context(self) -> None:
        import loom.daemon

        ctx = MagicMock(spec=DaemonContext)
        set_context(ctx)
        assert get_context() is ctx

        # Cleanup
        loom.daemon._ctx = None


class TestBuildAdaptors:
    async def test_builds_github_adaptor(self, tmp_loom_dir: Path) -> None:
        from loom.core.eventbus import EventBus
        from loom.core.mailbox import Mailbox
        from loom.state.store import Store

        store = Store(db_path=tmp_loom_dir / "data" / "test.db")
        await store.init()
        mailbox = Mailbox(store, EventBus())
        config = _make_config(tmp_loom_dir)

        sources = [{"kind": "github", "owner": "acme", "repo": "app"}]
        adaptors = _build_adaptors(sources, mailbox, config)

        assert len(adaptors) == 1
        assert adaptors[0].name == "github"
        await store.close()

    async def test_builds_gmail_adaptor(self, tmp_loom_dir: Path) -> None:
        pytest.importorskip("google.auth", reason="Gmail deps not installed")
        from loom.core.eventbus import EventBus
        from loom.core.mailbox import Mailbox
        from loom.state.store import Store

        store = Store(db_path=tmp_loom_dir / "data" / "test.db")
        await store.init()
        mailbox = Mailbox(store, EventBus())
        config = _make_config(tmp_loom_dir)

        secrets = tmp_loom_dir / "credentials" / "secret.json"
        secrets.parent.mkdir(parents=True, exist_ok=True)
        secrets.write_text("{}")

        sources = [{"kind": "gmail", "client_secrets": str(secrets)}]
        adaptors = _build_adaptors(sources, mailbox, config)

        assert len(adaptors) == 1
        assert adaptors[0].name == "gmail"
        await store.close()

    async def test_empty_sources(self, tmp_loom_dir: Path) -> None:
        from loom.core.eventbus import EventBus
        from loom.core.mailbox import Mailbox
        from loom.state.store import Store

        store = Store(db_path=tmp_loom_dir / "data" / "test.db")
        await store.init()
        mailbox = Mailbox(store, EventBus())
        config = _make_config(tmp_loom_dir)

        adaptors = _build_adaptors([], mailbox, config)
        assert adaptors == []
        await store.close()


class TestDaemonBootstrap:
    async def test_daemon_starts_and_stops_cleanly(self, tmp_loom_dir: Path) -> None:
        """Verify run_daemon bootstraps all components and shuts down gracefully."""
        import loom.daemon
        from loom.daemon import run_daemon

        config = _make_config(tmp_loom_dir)

        # Run daemon in a task, then send shutdown after a short delay
        async def _shutdown_soon():
            await asyncio.sleep(0.3)
            # Trigger shutdown via the event
            loop = asyncio.get_running_loop()
            loop.call_soon(signal.raise_signal, signal.SIGINT)

        task = asyncio.create_task(run_daemon(config))
        asyncio.create_task(_shutdown_soon())

        # Should complete without error
        await asyncio.wait_for(task, timeout=5.0)

        # Verify context is cleaned up
        assert loom.daemon._ctx is None or get_context().metrics.snapshot().online is False

    async def test_adaptor_failure_doesnt_crash_daemon(self, tmp_loom_dir: Path) -> None:
        """One adaptor failing to start shouldn't prevent the daemon from running."""
        from loom.daemon import run_daemon

        config = _make_config(
            tmp_loom_dir,
            sources=[{"kind": "github", "owner": "acme", "repo": "app"}],
        )

        async def _shutdown_soon():
            await asyncio.sleep(0.5)
            loop = asyncio.get_running_loop()
            loop.call_soon(signal.raise_signal, signal.SIGINT)

        task = asyncio.create_task(run_daemon(config))
        asyncio.create_task(_shutdown_soon())

        # Daemon should start (GitHub adaptor may fail without token, but daemon stays up)
        await asyncio.wait_for(task, timeout=5.0)


class TestCursorPersistence:
    async def test_save_and_restore_github_cursors(self, tmp_loom_dir: Path) -> None:
        from loom.adaptor.github import GitHubAdaptor, GitHubSourceConfig
        from loom.daemon import _restore_github_cursors, _save_github_cursors
        from loom.state.store import Store

        store = Store(db_path=tmp_loom_dir / "data" / "test.db")
        await store.init()

        gh = GitHubAdaptor()
        gh.add_source(GitHubSourceConfig(owner="acme", repo="app"))
        # Simulate some cursors
        gh._cursors = {"acme/app": "2024-01-01T00:00:00Z"}

        await _save_github_cursors(gh, store)

        # Create new adaptor and restore
        gh2 = GitHubAdaptor()
        gh2.add_source(GitHubSourceConfig(owner="acme", repo="app"))
        await _restore_github_cursors(gh2, store)

        assert gh2.get_cursors() == {"acme/app": "2024-01-01T00:00:00Z"}
        await store.close()
