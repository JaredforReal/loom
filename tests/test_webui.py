"""Tests for the FastAPI web UI layer."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import loom.daemon as daemon_mod
import loom.webui.app as webui_app
from loom.config import AgentSettings, DaemonSettings, LoomConfig, PathSettings
from loom.core.envelope import Envelope, EnvelopeStatus
from loom.core.eventbus import EventBus
from loom.core.mailbox import Mailbox
from loom.observability.metrics import MetricsCollector
from loom.state.store import Store


def _make_config(tmp_path: Path) -> LoomConfig:
    return LoomConfig(
        daemon=DaemonSettings(host="127.0.0.1", port=0),
        agent=AgentSettings(max_concurrent=2),
        sources=[],
        paths=PathSettings(
            data_dir=tmp_path / "data",
            policies_dir=tmp_path / "policies",
            prompts_dir=tmp_path / "prompts",
            credentials_dir=tmp_path / "credentials",
        ),
    )


@pytest.fixture
async def webui_ctx(tmp_loom_dir: Path):
    """Build a DaemonContext-shaped object wired to real Store/Mailbox."""
    store = Store(db_path=tmp_loom_dir / "data" / "test.db")
    await store.init()
    bus = EventBus()
    mailbox = Mailbox(store, bus)
    metrics = MetricsCollector()
    metrics.set_online(True)
    metrics.update(active_sessions=0, queue_backlog=0)

    config = _make_config(tmp_loom_dir)
    session_mgr = MagicMock(active_count=0)
    ctx = SimpleNamespace(
        config=config,
        store=store,
        bus=bus,
        mailbox=mailbox,
        metrics=metrics,
        session_mgr=session_mgr,
    )
    daemon_mod.set_context(ctx)  # type: ignore[arg-type]
    try:
        yield ctx
    finally:
        daemon_mod._ctx = None
        await store.close()


@pytest.fixture
def client(webui_ctx) -> TestClient:
    return TestClient(webui_app.app)


class TestStatus:
    def test_status_shape(self, client: TestClient) -> None:
        r = client.get("/api/status")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body["online"], bool)
        assert "active_sessions" in body
        assert "queue_backlog" in body


class TestEnvelopes:
    async def test_list_empty(self, client: TestClient) -> None:
        r = client.get("/api/envelopes")
        assert r.status_code == 200
        assert r.json() == []

    async def test_list_and_dismiss(self, client: TestClient, webui_ctx) -> None:
        env = Envelope(
            source="github",
            source_id="acme/app#1",
            title="test envelope",
            body="hi",
        )
        await webui_ctx.mailbox.receive(env)
        await webui_ctx.mailbox.update_status(env.id, EnvelopeStatus.IN_REVIEW)

        r = client.get("/api/envelopes")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["id"] == env.id
        assert items[0]["status"] == "in_review"

        r = client.post(f"/api/envelopes/{env.id}/dismiss")
        assert r.status_code == 200
        assert r.json()["status"] == "dismissed"

        r = client.get(f"/api/envelopes/{env.id}")
        assert r.json()["status"] == "dismissed"


class TestStaticFilesMount:
    """Guard: the StaticFiles mount must be gated by dist/ existing."""

    def test_dist_is_checked_at_import(self) -> None:
        # Sanity: module exposes _DIST pointing at loom/webui/dist
        assert webui_app._DIST.name == "dist"
        assert webui_app._DIST.parent.name == "webui"

    def test_mount_presence_matches_dist_existence(self) -> None:
        # Whichever state dist is currently in, /api routes must keep working.
        mounted = any(getattr(r, "name", None) == "spa" for r in webui_app.app.routes)
        assert mounted == webui_app._DIST.is_dir()

    def test_api_routes_unaffected_by_mount(self, client: TestClient) -> None:
        # Regardless of SPA presence, the API namespace still resolves.
        r = client.get("/api/status")
        assert r.status_code == 200


class TestSourcesEndpoint:
    async def test_sources_returns_config_entries(self, client: TestClient, webui_ctx) -> None:
        # Patch config.sources at runtime — list is empty by default.
        webui_ctx.config.sources = [{"kind": "github", "owner": "a", "repo": "b"}]
        r = client.get("/api/sources")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1
        assert body[0]["kind"] == "github"
        assert "unread" in body[0]

    async def test_sources_includes_name(self, client: TestClient, webui_ctx) -> None:
        webui_ctx.config.sources = [
            {"kind": "github", "owner": "octocat", "repo": "hello-world"},
            {"kind": "github", "owner": "acme", "repo": "api"},
        ]
        body = client.get("/api/sources").json()
        assert len(body) == 2
        assert body[0]["name"] == "octocat/hello-world"
        assert body[0]["unread"] == 0
        assert body[1]["name"] == "acme/api"
        assert body[1]["unread"] == 0

    async def test_sources_default_mode_is_active(self, client: TestClient, webui_ctx) -> None:
        webui_ctx.config.sources = [{"kind": "github", "owner": "a", "repo": "b"}]
        body = client.get("/api/sources").json()
        assert body[0]["mode"] == "active"

    async def test_sources_surfaces_explicit_mode(self, client: TestClient, webui_ctx) -> None:
        webui_ctx.config.sources = [
            {"kind": "github", "owner": "a", "repo": "b", "mode": "fetch-only"}
        ]
        body = client.get("/api/sources").json()
        assert body[0]["mode"] == "fetch-only"


class TestSourceModeEndpoint:
    async def test_patch_mode_writes_config(
        self,
        client: TestClient,
        webui_ctx,
        tmp_loom_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import loom.config as config_mod

        monkeypatch.setattr(config_mod, "DEFAULT_LOOM_DIR", tmp_loom_dir)
        webui_ctx.config.sources = [{"kind": "github", "owner": "a", "repo": "b"}]

        r = client.patch("/api/sources/github/mode", json={"mode": "fetch-only"})
        assert r.status_code == 200
        body = r.json()
        assert body == {
            "ok": True,
            "kind": "github",
            "mode": "fetch-only",
            "updated": 1,
        }

        # In-memory config reflects the change
        assert webui_ctx.config.sources[0]["mode"] == "fetch-only"
        # Written to config.yaml
        written = (tmp_loom_dir / "config.yaml").read_text()
        assert "mode: fetch-only" in written

    async def test_patch_mode_invalid_returns_400(self, client: TestClient, webui_ctx) -> None:
        webui_ctx.config.sources = [{"kind": "github", "owner": "a", "repo": "b"}]
        r = client.patch("/api/sources/github/mode", json={"mode": "nonsense"})
        assert r.status_code == 400
        assert "invalid" in r.json()["error"].lower()
        # Config untouched
        assert "mode" not in webui_ctx.config.sources[0]

    async def test_patch_mode_unknown_kind_returns_404(self, client: TestClient, webui_ctx) -> None:
        webui_ctx.config.sources = [{"kind": "github", "owner": "a", "repo": "b"}]
        r = client.patch("/api/sources/nonexistent/mode", json={"mode": "paused"})
        assert r.status_code == 404

    async def test_patch_mode_all_valid_modes(
        self,
        client: TestClient,
        webui_ctx,
        tmp_loom_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import loom.config as config_mod

        monkeypatch.setattr(config_mod, "DEFAULT_LOOM_DIR", tmp_loom_dir)
        webui_ctx.config.sources = [{"kind": "github", "owner": "a", "repo": "b"}]

        for mode in ("active", "fetch-only", "paused"):
            r = client.patch("/api/sources/github/mode", json={"mode": mode})
            assert r.status_code == 200, f"mode={mode} failed"
            assert webui_ctx.config.sources[0]["mode"] == mode


class TestContextUnset:
    """If daemon isn't running, WebUI endpoints should bubble a clean error."""

    def test_endpoint_without_context_raises(self) -> None:
        from loom.api_server import app as api_app

        api_app.state.ctx = None
        client = TestClient(webui_app.app, raise_server_exceptions=False)
        r = client.get("/api/status")
        assert r.status_code == 500
        _ = MagicMock  # kept for future expansion
