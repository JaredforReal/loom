"""Tests for the policies management endpoints in the WebUI API."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import loom.daemon as daemon_mod
import loom.webui.app as webui_app
from loom.config import AgentSettings, DaemonSettings, LoomConfig, PathSettings
from loom.core.eventbus import EventBus
from loom.core.mailbox import Mailbox
from loom.observability.metrics import MetricsCollector
from loom.orchestrator.policy import PolicyEngine
from loom.state.store import Store

SAMPLE_POLICY = """rules:
  - name: "Test rule"
    match:
      source: github
    action:
      priority: 2
      prompt: "test_prompt"
"""

ANOTHER_POLICY = """rules:
  - name: "Another rule"
    match:
      source: gmail
    action:
      priority: 1
"""


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
    store = Store(db_path=tmp_loom_dir / "data" / "test.db")
    await store.init()
    bus = EventBus()
    mailbox = Mailbox(store, bus)
    metrics = MetricsCollector()

    config = _make_config(tmp_loom_dir)

    bundled_dir = tmp_loom_dir / "bundled_policies"
    bundled_dir.mkdir()
    (bundled_dir / "default.yaml").write_text(
        'rules:\n  - name: "Bundled default"\n    match: {source: github}\n'
        "    action: {priority: 0}\n"
    )

    policy_engine = PolicyEngine(
        policy_dir=config.paths.policies_dir,
        bundled_dir=bundled_dir,
    )

    ctx = SimpleNamespace(
        config=config,
        store=store,
        bus=bus,
        mailbox=mailbox,
        metrics=metrics,
        policy_engine=policy_engine,
    )
    daemon_mod.set_context(ctx)  # type: ignore[arg-type]
    try:
        yield ctx
    finally:
        await store.close()


@pytest.fixture
def client(webui_ctx) -> TestClient:
    return TestClient(webui_app.app)


class TestListPolicies:
    def test_lists_user_and_bundled(self, client: TestClient, webui_ctx) -> None:
        (webui_ctx.config.paths.policies_dir / "mine.yaml").write_text(SAMPLE_POLICY)

        r = client.get("/api/settings/policies")
        assert r.status_code == 200
        items = r.json()
        names = [(it["name"], it["source"]) for it in items]
        assert ("mine.yaml", "user") in names
        assert ("default.yaml", "bundled") in names

    def test_returns_content(self, client: TestClient, webui_ctx) -> None:
        (webui_ctx.config.paths.policies_dir / "mine.yaml").write_text(SAMPLE_POLICY)
        body = client.get("/api/settings/policies").json()
        user_entry = next(b for b in body if b["name"] == "mine.yaml")
        assert "Test rule" in user_entry["content"]


class TestGetPolicy:
    def test_get_user_policy(self, client: TestClient, webui_ctx) -> None:
        (webui_ctx.config.paths.policies_dir / "mine.yaml").write_text(SAMPLE_POLICY)
        r = client.get("/api/settings/policies/mine.yaml")
        assert r.status_code == 200
        assert r.json()["source"] == "user"
        assert "Test rule" in r.json()["content"]

    def test_get_bundled_policy(self, client: TestClient) -> None:
        r = client.get("/api/settings/policies/default.yaml")
        assert r.status_code == 200
        assert r.json()["source"] == "bundled"

    def test_get_unknown_returns_404(self, client: TestClient) -> None:
        r = client.get("/api/settings/policies/nonexistent.yaml")
        assert r.status_code == 404

    def test_path_traversal_rejected(self, client: TestClient) -> None:
        r = client.get("/api/settings/policies/..%2Fevil.yaml")
        assert r.status_code in (400, 404)


class TestSavePolicy:
    def test_save_creates_file_and_reloads(self, client: TestClient, webui_ctx) -> None:
        r = client.put(
            "/api/settings/policies/mine.yaml",
            json={"content": SAMPLE_POLICY},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["saved"] == "mine.yaml"
        assert body["rules"] >= 2  # 1 user + 1 bundled

        path = webui_ctx.config.paths.policies_dir / "mine.yaml"
        assert path.exists()
        assert "Test rule" in path.read_text()

        rules = webui_ctx.policy_engine.list_rules()
        assert any(r["name"] == "Test rule" for r in rules)

    def test_save_overwrites_existing(self, client: TestClient, webui_ctx) -> None:
        path = webui_ctx.config.paths.policies_dir / "mine.yaml"
        path.write_text(SAMPLE_POLICY)
        client.put("/api/settings/policies/mine.yaml", json={"content": ANOTHER_POLICY})
        assert "Another rule" in path.read_text()

    def test_invalid_yaml_returns_400(self, client: TestClient, webui_ctx) -> None:
        r = client.put(
            "/api/settings/policies/bad.yaml",
            json={"content": "rules: [invalid: yaml: ::"},
        )
        assert r.status_code == 400
        assert "yaml" in r.json()["error"].lower()
        # File should not be written
        assert not (webui_ctx.config.paths.policies_dir / "bad.yaml").exists()

    def test_non_object_yaml_rejected(self, client: TestClient) -> None:
        r = client.put(
            "/api/settings/policies/list.yaml",
            json={"content": "- one\n- two\n"},
        )
        assert r.status_code == 400

    def test_path_traversal_rejected(self, client: TestClient) -> None:
        r = client.put(
            "/api/settings/policies/..%2Fevil.yaml",
            json={"content": SAMPLE_POLICY},
        )
        assert r.status_code in (400, 404, 405)


class TestDeletePolicy:
    def test_delete_removes_file_and_reloads(self, client: TestClient, webui_ctx) -> None:
        path = webui_ctx.config.paths.policies_dir / "mine.yaml"
        path.write_text(SAMPLE_POLICY)
        webui_ctx.policy_engine.reload()
        assert any(r["name"] == "Test rule" for r in webui_ctx.policy_engine.list_rules())

        r = client.delete("/api/settings/policies/mine.yaml")
        assert r.status_code == 200
        assert not path.exists()
        # After reload, "Test rule" should be gone
        assert not any(r["name"] == "Test rule" for r in webui_ctx.policy_engine.list_rules())

    def test_delete_unknown_returns_404(self, client: TestClient) -> None:
        r = client.delete("/api/settings/policies/nonexistent.yaml")
        assert r.status_code == 404


class TestReloadPolicy:
    def test_reload_picks_up_external_changes(self, client: TestClient, webui_ctx) -> None:
        # Write a file to disk WITHOUT going through the API
        (webui_ctx.config.paths.policies_dir / "external.yaml").write_text(SAMPLE_POLICY)
        # Engine still has only bundled rules
        before = len(webui_ctx.policy_engine.list_rules())

        r = client.post("/api/settings/policies/reload")
        assert r.status_code == 200
        assert r.json()["rules"] > before


class TestSchema:
    def test_schema_returns_known_fields(self, client: TestClient, webui_ctx) -> None:
        (webui_ctx.config.paths.prompts_dir / "my_prompt.md").write_text("hello")

        r = client.get("/api/settings/policies/schema")
        assert r.status_code == 200
        body = r.json()
        assert "github" in body["sources"]
        assert "Read" in body["tools"]
        assert "my_prompt" in body["prompts"]
        assert "priority" in body["action_fields"]
