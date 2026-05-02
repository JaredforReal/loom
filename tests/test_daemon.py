"""Tests for loom.daemon module."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from loom.config import AgentSettings, DaemonSettings, LoomConfig, PathSettings
from loom.daemon import (
    DaemonContext,
    _build_adaptors,
    _remove_pid,
    _resolve_proxy,
    _write_pid,
    get_context,
    set_context,
    setup_logging,
)


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


class TestPidManagement:
    def test_write_and_remove_pid(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "loom.pid"
        _write_pid(pid_file)
        assert pid_file.exists()
        assert int(pid_file.read_text()) == os.getpid()

        _remove_pid(pid_file)
        assert not pid_file.exists()

    def test_remove_pid_missing_ok(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "nonexistent.pid"
        _remove_pid(pid_file)  # should not raise

    def test_write_pid_creates_parent(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "deep" / "nested" / "loom.pid"
        _write_pid(pid_file)
        assert pid_file.exists()


class TestSetupLogging:
    def test_file_handler_always_added(self, tmp_path: Path) -> None:
        log_path = tmp_path / "test.log"
        setup_logging(log_path, foreground=False)

        loom_logger = logging.getLogger("loom")
        handler_types = [type(h).__name__ for h in loom_logger.handlers]
        assert "RotatingFileHandler" in handler_types

        # Cleanup
        loom_logger.handlers.clear()

    def test_console_handler_only_in_foreground(self, tmp_path: Path) -> None:
        log_path = tmp_path / "test.log"

        # Background: no console handler
        setup_logging(log_path, foreground=False)
        loom_logger = logging.getLogger("loom")
        handler_types = [type(h).__name__ for h in loom_logger.handlers]
        assert "StreamHandler" not in handler_types
        loom_logger.handlers.clear()

        # Foreground: has console handler
        setup_logging(log_path, foreground=True)
        loom_logger = logging.getLogger("loom")
        handler_types = [type(h).__name__ for h in loom_logger.handlers]
        assert "StreamHandler" in handler_types
        loom_logger.handlers.clear()


class TestResolveProxy:
    def test_config_proxy_takes_priority(self) -> None:
        config = _make_config(Path("/tmp"))
        config.daemon.proxy = "http://config-proxy:8080"
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://env-proxy:8080"}):
            assert _resolve_proxy(config) == "http://config-proxy:8080"

    def test_falls_back_to_https_proxy_env(self) -> None:
        config = _make_config(Path("/tmp"))
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://env-proxy:8080"}, clear=False):
            assert _resolve_proxy(config) == "http://env-proxy:8080"

    def test_falls_back_to_http_proxy_env(self) -> None:
        config = _make_config(Path("/tmp"))
        env = {"HTTP_PROXY": "http://env-proxy:8080"}
        with patch.dict(os.environ, env, clear=False):
            # Make sure HTTPS_PROXY is not set
            os.environ.pop("HTTPS_PROXY", None)
            os.environ.pop("https_proxy", None)
            assert _resolve_proxy(config) == "http://env-proxy:8080"

    def test_returns_none_when_nothing_set(self) -> None:
        config = _make_config(Path("/tmp"))
        with patch.dict(os.environ, {}, clear=False):
            for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
                os.environ.pop(key, None)
            assert _resolve_proxy(config) is None


class TestPortConflict:
    async def test_port_in_use_causes_exit(self, tmp_loom_dir: Path) -> None:
        # Bind to a port to occupy it
        import socket

        from loom.daemon import run_daemon

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.listen(1)

        config = _make_config(tmp_loom_dir)
        config.daemon.port = port

        with pytest.raises(SystemExit, match="1"):
            await run_daemon(config)

        sock.close()


class TestDuplicateDaemon:
    async def test_refuses_when_pid_exists(self, tmp_loom_dir: Path) -> None:
        from loom.daemon import run_daemon

        config = _make_config(tmp_loom_dir)
        pid_path = config.paths.data_dir / "loom.pid"
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()))

        with pytest.raises(SystemExit, match="1"):
            await run_daemon(config)
