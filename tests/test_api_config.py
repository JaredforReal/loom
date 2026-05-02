"""Tests for the config.yaml management endpoints in the WebUI API."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import loom.config as config_mod
import loom.daemon as daemon_mod
import loom.webui.app as webui_app
from loom.config import AgentSettings, DaemonSettings, LoomConfig, PathSettings
from loom.core.eventbus import EventBus
from loom.core.mailbox import Mailbox
from loom.observability.metrics import MetricsCollector
from loom.state.store import Store

INITIAL_CONFIG = """daemon:
  host: 127.0.0.1
  port: 8732
agent:
  max_concurrent: 3
  model: sonnet
sources:
- kind: github
  owner: acme
  repo: app
groups:
  research: arxiv_policy
"""


def _make_config(tmp_path: Path) -> LoomConfig:
    return LoomConfig(
        daemon=DaemonSettings(host="127.0.0.1", port=8732),
        agent=AgentSettings(max_concurrent=3, model="sonnet"),
        sources=[{"kind": "github", "owner": "acme", "repo": "app"}],
        paths=PathSettings(
            data_dir=tmp_path / "data",
            policies_dir=tmp_path / "policies",
            prompts_dir=tmp_path / "prompts",
            credentials_dir=tmp_path / "credentials",
        ),
    )


@pytest.fixture
async def webui_ctx(tmp_loom_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config_mod, "DEFAULT_LOOM_DIR", tmp_loom_dir)

    store = Store(db_path=tmp_loom_dir / "data" / "test.db")
    await store.init()
    bus = EventBus()
    mailbox = Mailbox(store, bus)
    metrics = MetricsCollector()

    config = _make_config(tmp_loom_dir)
    (tmp_loom_dir / "config.yaml").write_text(INITIAL_CONFIG)

    ctx = SimpleNamespace(
        config=config,
        store=store,
        bus=bus,
        mailbox=mailbox,
        metrics=metrics,
    )
    daemon_mod.set_context(ctx)  # type: ignore[arg-type]
    try:
        yield ctx
    finally:
        await store.close()


@pytest.fixture
def client(webui_ctx) -> TestClient:
    return TestClient(webui_app.app)


class TestGetConfig:
    def test_returns_existing_content(self, client: TestClient, webui_ctx) -> None:
        r = client.get("/api/settings/config")
        assert r.status_code == 200
        body = r.json()
        assert "config.yaml" in body["path"]
        assert "daemon:" in body["content"]

    def test_empty_when_missing(self, client: TestClient, tmp_loom_dir: Path) -> None:
        (tmp_loom_dir / "config.yaml").unlink()
        r = client.get("/api/settings/config")
        assert r.status_code == 200
        assert r.json()["content"] == ""


class TestSaveConfig:
    def test_save_writes_file_and_hot_reloads_groups(
        self, client: TestClient, webui_ctx, tmp_loom_dir: Path
    ) -> None:
        modified = INITIAL_CONFIG.replace("research: arxiv_policy", "research: new_policy")
        r = client.put("/api/settings/config", json={"content": modified})
        assert r.status_code == 200
        body = r.json()
        assert body["saved"] is True
        assert "groups" in body["changed"]
        # groups change is hot-reloadable, not in restart_required
        assert "groups" not in body["restart_required"]

        # File on disk
        assert "new_policy" in (tmp_loom_dir / "config.yaml").read_text()
        # ctx.config swapped
        assert webui_ctx.config.groups["research"] == "new_policy"

    def test_changing_sources_marks_restart_required(self, client: TestClient, webui_ctx) -> None:
        modified = INITIAL_CONFIG.replace(
            "sources:\n- kind: github\n  owner: acme\n  repo: app\n",
            "sources:\n- kind: github\n  owner: acme\n  repo: app\n"
            "- kind: rss\n  url: https://example.com/feed\n",
        )
        r = client.put("/api/settings/config", json={"content": modified})
        assert r.status_code == 200
        body = r.json()
        assert "sources" in body["changed"]
        assert "sources" in body["restart_required"]

    def test_changing_daemon_marks_restart_required(self, client: TestClient) -> None:
        modified = INITIAL_CONFIG.replace("port: 8732", "port: 9000")
        r = client.put("/api/settings/config", json={"content": modified})
        assert r.status_code == 200
        body = r.json()
        assert "daemon" in body["restart_required"]

    def test_invalid_yaml_returns_400(
        self, client: TestClient, webui_ctx, tmp_loom_dir: Path
    ) -> None:
        before = (tmp_loom_dir / "config.yaml").read_text()
        r = client.put("/api/settings/config", json={"content": "daemon: [: invalid: ::"})
        assert r.status_code == 400
        # File untouched
        assert (tmp_loom_dir / "config.yaml").read_text() == before
        # ctx.config untouched
        assert webui_ctx.config.daemon.port == 8732

    def test_non_object_yaml_rejected(self, client: TestClient) -> None:
        r = client.put("/api/settings/config", json={"content": "- one\n- two\n"})
        assert r.status_code == 400

    def test_non_string_content_rejected(self, client: TestClient) -> None:
        r = client.put("/api/settings/config", json={"content": 123})
        assert r.status_code == 400


class TestReloadConfig:
    def test_reload_picks_up_external_changes(
        self, client: TestClient, webui_ctx, tmp_loom_dir: Path
    ) -> None:
        # Write directly to disk without going through the API
        modified = INITIAL_CONFIG.replace("model: sonnet", "model: opus")
        (tmp_loom_dir / "config.yaml").write_text(modified)
        # ctx.config still has old value
        assert webui_ctx.config.agent.model == "sonnet"

        r = client.post("/api/settings/config/reload")
        assert r.status_code == 200
        body = r.json()
        assert "agent" in body["changed"]
        assert webui_ctx.config.agent.model == "opus"
