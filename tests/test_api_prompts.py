"""Tests for the prompts management endpoints in the WebUI API."""

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
from loom.orchestrator.session import SessionManager
from loom.state.store import Store

SAMPLE_PROMPT = "# My prompt\n\nDo something useful with {{title}}.\n"
ANOTHER_PROMPT = "# Different\n\nAnother prompt body.\n"


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

    bundled_dir = tmp_loom_dir / "bundled_prompts"
    bundled_dir.mkdir()
    (bundled_dir / "default.md").write_text("# Bundled default\n")

    session_mgr = SessionManager(
        prompt_dir=config.paths.prompts_dir,
        bundled_prompt_dir=bundled_dir,
    )

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
        await store.close()


@pytest.fixture
def client(webui_ctx) -> TestClient:
    return TestClient(webui_app.app)


class TestListPrompts:
    def test_lists_user_and_bundled(self, client: TestClient, webui_ctx) -> None:
        (webui_ctx.config.paths.prompts_dir / "mine.md").write_text(SAMPLE_PROMPT)

        r = client.get("/api/settings/prompts")
        assert r.status_code == 200
        items = r.json()
        names = [(it["name"], it["source"]) for it in items]
        assert ("mine.md", "user") in names
        assert ("default.md", "bundled") in names

    def test_returns_content(self, client: TestClient, webui_ctx) -> None:
        (webui_ctx.config.paths.prompts_dir / "mine.md").write_text(SAMPLE_PROMPT)
        body = client.get("/api/settings/prompts").json()
        user_entry = next(b for b in body if b["name"] == "mine.md")
        assert "My prompt" in user_entry["content"]


class TestGetPrompt:
    def test_get_user_prompt(self, client: TestClient, webui_ctx) -> None:
        (webui_ctx.config.paths.prompts_dir / "mine.md").write_text(SAMPLE_PROMPT)
        r = client.get("/api/settings/prompts/mine.md")
        assert r.status_code == 200
        assert r.json()["source"] == "user"
        assert "My prompt" in r.json()["content"]

    def test_get_bundled_prompt(self, client: TestClient) -> None:
        r = client.get("/api/settings/prompts/default.md")
        assert r.status_code == 200
        assert r.json()["source"] == "bundled"

    def test_get_unknown_returns_404(self, client: TestClient) -> None:
        r = client.get("/api/settings/prompts/nonexistent.md")
        assert r.status_code == 404

    def test_path_traversal_rejected(self, client: TestClient) -> None:
        r = client.get("/api/settings/prompts/..%2Fevil.md")
        assert r.status_code in (400, 404)


class TestSavePrompt:
    def test_save_creates_file_and_reloads(self, client: TestClient, webui_ctx) -> None:
        r = client.put(
            "/api/settings/prompts/mine.md",
            json={"content": SAMPLE_PROMPT},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["saved"] == "mine.md"
        assert body["templates"] >= 2  # 1 user + 1 bundled

        path = webui_ctx.config.paths.prompts_dir / "mine.md"
        assert path.exists()
        assert "My prompt" in path.read_text()

        names = webui_ctx.session_mgr.list_template_names()
        assert "mine" in names

    def test_save_overwrites_existing(self, client: TestClient, webui_ctx) -> None:
        path = webui_ctx.config.paths.prompts_dir / "mine.md"
        path.write_text(SAMPLE_PROMPT)
        client.put("/api/settings/prompts/mine.md", json={"content": ANOTHER_PROMPT})
        assert "Different" in path.read_text()

    def test_non_string_content_rejected(self, client: TestClient) -> None:
        r = client.put("/api/settings/prompts/x.md", json={"content": 123})
        assert r.status_code == 400

    def test_non_md_extension_rejected(self, client: TestClient) -> None:
        r = client.put(
            "/api/settings/prompts/x.txt",
            json={"content": SAMPLE_PROMPT},
        )
        assert r.status_code == 400

    def test_path_traversal_rejected(self, client: TestClient) -> None:
        r = client.put(
            "/api/settings/prompts/..%2Fevil.md",
            json={"content": SAMPLE_PROMPT},
        )
        assert r.status_code in (400, 404, 405)


class TestDeletePrompt:
    def test_delete_removes_file_and_reloads(self, client: TestClient, webui_ctx) -> None:
        path = webui_ctx.config.paths.prompts_dir / "mine.md"
        path.write_text(SAMPLE_PROMPT)
        webui_ctx.session_mgr.reload_prompts()
        assert "mine" in webui_ctx.session_mgr.list_template_names()

        r = client.delete("/api/settings/prompts/mine.md")
        assert r.status_code == 200
        assert not path.exists()
        assert "mine" not in webui_ctx.session_mgr.list_template_names()

    def test_delete_unknown_returns_404(self, client: TestClient) -> None:
        r = client.delete("/api/settings/prompts/nonexistent.md")
        assert r.status_code == 404


class TestReloadPrompts:
    def test_reload_picks_up_external_changes(self, client: TestClient, webui_ctx) -> None:
        (webui_ctx.config.paths.prompts_dir / "external.md").write_text(SAMPLE_PROMPT)
        before = len(webui_ctx.session_mgr.list_template_names())

        r = client.post("/api/settings/prompts/reload")
        assert r.status_code == 200
        assert r.json()["templates"] > before


class TestUserOverridesBundled:
    def test_user_prompt_with_same_name_overrides_bundled(
        self, client: TestClient, webui_ctx
    ) -> None:
        # Bundled has "default.md"; create a user file with the same name
        (webui_ctx.config.paths.prompts_dir / "default.md").write_text("# User override\n")
        client.post("/api/settings/prompts/reload")
        # The in-memory template "default" should now have user content
        ctx = webui_ctx
        assert "User override" in ctx.session_mgr.get_prompt_template("default")
