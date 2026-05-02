"""Tests for prompt loading, SafeDict interpolation, policy layering, and
new PolicyAction fields."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from loom.core.envelope import Envelope
from loom.orchestrator.dispatcher import _SafeDict
from loom.orchestrator.policy import PolicyAction, PolicyEngine
from loom.orchestrator.session import SessionManager

# ---------------------------------------------------------------------------
# SafeDict
# ---------------------------------------------------------------------------


class TestSafeDict:
    def test_returns_empty_string_for_missing_keys(self) -> None:
        d = _SafeDict({"a": 1})
        assert d["a"] == 1
        assert d["missing"] == ""

    def test_nested_safedict(self) -> None:
        inner = _SafeDict({"user": "alice"})
        outer = _SafeDict({"metadata": inner})
        assert outer["metadata"]["user"] == "alice"
        assert outer["metadata"]["missing"] == ""

    def test_format_map_with_missing_keys(self) -> None:
        template = "Hello {name}, your repo is {metadata[repo]}"
        ctx = _SafeDict({"name": "test", "metadata": _SafeDict({"repo": "acme/app"})})
        assert template.format_map(ctx) == "Hello test, your repo is acme/app"

    def test_format_map_missing_metadata_returns_empty(self) -> None:
        template = "Author: {metadata[user]}"
        ctx = _SafeDict({"metadata": _SafeDict({})})
        assert template.format_map(ctx) == "Author: "


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


class TestPromptLoading:
    def test_loads_bundled_prompts(self, tmp_path: Path) -> None:
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "prompt_test.md").write_text("Hello {title}")

        mgr = SessionManager(prompt_dir=tmp_path / "empty", bundled_prompt_dir=bundled)
        assert mgr.get_prompt_template("prompt_test") == "Hello {title}"

    def test_user_overrides_bundled(self, tmp_path: Path) -> None:
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "prompt_test.md").write_text("bundled version")

        user = tmp_path / "user"
        user.mkdir()
        (user / "prompt_test.md").write_text("user override")

        mgr = SessionManager(prompt_dir=user, bundled_prompt_dir=bundled)
        assert mgr.get_prompt_template("prompt_test") == "user override"

    def test_per_source_prompt(self, tmp_path: Path) -> None:
        user = tmp_path / "user"
        user.mkdir()
        github_dir = user / "github"
        github_dir.mkdir()
        (github_dir / "acme-app.md").write_text("per-repo prompt for acme")

        mgr = SessionManager(prompt_dir=user, bundled_prompt_dir=None)
        assert mgr.get_prompt_template("github/acme-app") == "per-repo prompt for acme"

    def test_fallback_returns_name_when_not_found(self, tmp_path: Path) -> None:
        mgr = SessionManager(prompt_dir=tmp_path, bundled_prompt_dir=None)
        assert mgr.get_prompt_template("nonexistent") == "nonexistent"

    def test_all_layers_together(self, tmp_path: Path) -> None:
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "prompt_test.md").write_text("bundled")
        (bundled / "prompt_other.md").write_text("other bundled")

        user = tmp_path / "user"
        user.mkdir()
        (user / "prompt_test.md").write_text("user override")
        src_dir = user / "github"
        src_dir.mkdir()
        (src_dir / "my-repo.md").write_text("per-source")

        mgr = SessionManager(prompt_dir=user, bundled_prompt_dir=bundled)
        assert mgr.get_prompt_template("prompt_test") == "user override"
        assert mgr.get_prompt_template("prompt_other") == "other bundled"
        assert mgr.get_prompt_template("github/my-repo") == "per-source"
        assert mgr.get_prompt_template("missing") == "missing"

    def test_loads_actual_bundled_prompts(self) -> None:
        bundled_dir = Path(__file__).parent.parent / "loom" / "prompts"
        if not bundled_dir.exists():
            pytest.skip("No bundled prompts directory")
        mgr = SessionManager(
            prompt_dir=Path("/nonexistent"),
            bundled_prompt_dir=bundled_dir,
        )
        assert mgr.get_prompt_template("prompt_github_issue") != "prompt_github_issue"
        assert mgr.get_prompt_template("prompt_gmail") != "prompt_gmail"


# ---------------------------------------------------------------------------
# Policy layering
# ---------------------------------------------------------------------------


class TestPolicyLayering:
    def test_loads_bundled_policies(self, tmp_path: Path) -> None:
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "default.yaml").write_text(
            yaml.dump(
                {
                    "rules": [
                        {
                            "name": "default rule",
                            "match": {"source": "github"},
                            "action": {"priority": 1},
                        }
                    ]
                }
            )
        )

        engine = PolicyEngine(policy_dir=tmp_path / "empty", bundled_dir=bundled)
        envelope = Envelope(source="github")
        action = engine.evaluate(envelope)
        assert action is not None
        assert action.priority == 1

    def test_user_rules_match_before_bundled(self, tmp_path: Path) -> None:
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        (bundled / "default.yaml").write_text(
            yaml.dump(
                {
                    "rules": [
                        {
                            "name": "bundled",
                            "match": {"source": "github"},
                            "action": {"priority": 1},
                        }
                    ]
                }
            )
        )

        user = tmp_path / "user"
        user.mkdir()
        (user / "override.yaml").write_text(
            yaml.dump(
                {
                    "rules": [
                        {
                            "name": "user override",
                            "match": {"source": "github"},
                            "action": {"priority": 3},
                        }
                    ]
                }
            )
        )

        engine = PolicyEngine(policy_dir=user, bundled_dir=bundled)
        envelope = Envelope(source="github")
        action = engine.evaluate(envelope)
        assert action is not None
        assert action.priority == 3  # User rule wins

    def test_new_policy_action_fields(self, tmp_path: Path) -> None:
        policy_dir = tmp_path / "policies"
        policy_dir.mkdir()
        (policy_dir / "test.yaml").write_text(
            yaml.dump(
                {
                    "rules": [
                        {
                            "name": "vllm rule",
                            "match": {
                                "source": "github",
                                "source_id_pattern": "vllm-project/vllm#",
                            },
                            "action": {
                                "priority": 2,
                                "prompt": "github/vllm",
                                "skills": ["vllm-expert"],
                                "cwd": "/path/to/vllm",
                                "model": "sonnet",
                                "max_turns": 5,
                            },
                        }
                    ]
                }
            )
        )

        engine = PolicyEngine(policy_dir=policy_dir)
        envelope = Envelope(source="github", source_id="vllm-project/vllm#42")
        action = engine.evaluate(envelope)
        assert action is not None
        assert action.skills == ["vllm-expert"]
        assert action.cwd == "/path/to/vllm"
        assert action.model == "sonnet"
        assert action.max_turns == 5
        assert action.prompt == "github/vllm"

    def test_loads_actual_bundled_policies(self) -> None:
        bundled_dir = Path(__file__).parent.parent / "loom" / "policies"
        if not bundled_dir.exists():
            pytest.skip("No bundled policies directory")
        engine = PolicyEngine(policy_dir=Path("/nonexistent"), bundled_dir=bundled_dir)
        # Should match GitHub envelopes
        envelope = Envelope(source="github")
        action = engine.evaluate(envelope)
        assert action is not None

    def test_empty_dirs_no_error(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        engine = PolicyEngine(policy_dir=empty, bundled_dir=None)
        envelope = Envelope(source="github")
        assert engine.evaluate(envelope) is None


# ---------------------------------------------------------------------------
# Dispatcher prompt building
# ---------------------------------------------------------------------------


class TestDispatcherPromptBuilding:
    def test_build_task_prompt_with_metadata(self) -> None:
        from unittest.mock import MagicMock

        from loom.core.eventbus import EventBus
        from loom.orchestrator.dispatcher import Dispatcher

        bus = EventBus()
        sessions = MagicMock()
        policy = MagicMock()
        mailbox = MagicMock()

        disp = Dispatcher(bus, sessions, policy, mailbox)

        template = "Author: {metadata[user]}, Link: {metadata[html_url]}\n{body}"
        sessions.get_prompt_template.return_value = template

        envelope = Envelope(
            source="github",
            title="Test issue",
            body="Bug report body",
            metadata={"user": "alice", "html_url": "https://github.com/acme/app/issues/1"},
        )
        action = PolicyAction(prompt="test_template")

        result = disp._build_task_prompt(envelope, action)
        assert "Author: alice" in result
        assert "https://github.com/acme/app/issues/1" in result
        assert "Bug report body" in result

    def test_build_task_prompt_missing_metadata_graceful(self) -> None:
        from unittest.mock import MagicMock

        from loom.core.eventbus import EventBus
        from loom.orchestrator.dispatcher import Dispatcher

        bus = EventBus()
        sessions = MagicMock()
        policy = MagicMock()
        mailbox = MagicMock()

        disp = Dispatcher(bus, sessions, policy, mailbox)

        template = "Author: {metadata[user]}, Repo: {metadata[repo]}"
        sessions.get_prompt_template.return_value = template

        envelope = Envelope(source="github", title="Test", metadata={})
        action = PolicyAction(prompt="test_template")

        result = disp._build_task_prompt(envelope, action)
        assert "Author: , Repo: " in result  # No KeyError, empty strings

    def test_fallback_prompt_when_template_not_found(self) -> None:
        from unittest.mock import MagicMock

        from loom.core.eventbus import EventBus
        from loom.orchestrator.dispatcher import Dispatcher

        bus = EventBus()
        sessions = MagicMock()
        policy = MagicMock()
        mailbox = MagicMock()

        disp = Dispatcher(bus, sessions, policy, mailbox)

        # get_prompt_template returns the name (template not found)
        sessions.get_prompt_template.return_value = "nonexistent_template"

        envelope = Envelope(source="github", title="Login bug", body="Fix the login")
        action = PolicyAction(prompt="nonexistent_template")

        result = disp._build_task_prompt(envelope, action)
        assert "Login bug" in result
        assert "Fix the login" in result


# ---------------------------------------------------------------------------
# Agent toggle and concurrency
# ---------------------------------------------------------------------------


class TestAgentToggle:
    async def test_agent_disabled_skips_dispatch(self) -> None:
        from unittest.mock import MagicMock

        from loom.core.eventbus import EventBus
        from loom.orchestrator.dispatcher import Dispatcher

        bus = EventBus()
        sessions = MagicMock()
        policy = MagicMock()
        mailbox = MagicMock()

        disp = Dispatcher(bus, sessions, policy, mailbox, agent_enabled=False)
        assert disp.agent_enabled is False

        envelope = Envelope(source="github", title="Test")
        # Should not evaluate policy or dispatch
        await disp._on_new_envelope("new_envelope", envelope)
        policy.evaluate.assert_not_called()

    async def test_agent_enabled_dispatches(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from loom.core.eventbus import EventBus
        from loom.orchestrator.dispatcher import Dispatcher

        bus = EventBus()
        sessions = MagicMock()
        policy = MagicMock()
        mailbox = MagicMock()
        mailbox.update_status = AsyncMock()
        mailbox._store = MagicMock()

        action = PolicyAction(prompt="test")
        policy.evaluate.return_value = action
        sessions.get_prompt_template.return_value = "test"
        sessions.spawn = AsyncMock()

        disp = Dispatcher(bus, sessions, policy, mailbox, agent_enabled=True)

        envelope = Envelope(source="github", title="Test")
        await disp._on_new_envelope("new_envelope", envelope)
        policy.evaluate.assert_called_once()
        sessions.spawn.assert_called_once()

    def test_set_agent_enabled_toggles(self) -> None:
        from unittest.mock import MagicMock

        from loom.core.eventbus import EventBus
        from loom.orchestrator.dispatcher import Dispatcher

        bus = EventBus()
        sessions = MagicMock()
        policy = MagicMock()
        mailbox = MagicMock()

        disp = Dispatcher(bus, sessions, policy, mailbox, agent_enabled=False)
        assert disp.agent_enabled is False

        # Use direct attribute to avoid asyncio.create_task in sync test
        disp._agent_enabled = True
        assert disp.agent_enabled is True

        disp._agent_enabled = False
        assert disp.agent_enabled is False


class TestSessionConcurrency:
    async def test_semaphore_limits_concurrent_sessions(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from loom.orchestrator.session import SessionManager, SessionStatus

        mgr = SessionManager(max_concurrent=2, prompt_dir=Path("/nonexistent"))

        started: list[str] = []
        finish_events: list[asyncio.Event] = []

        async def mock_run(session, prompt):
            started.append(session.id)
            event = asyncio.Event()
            finish_events.append(event)
            await event.wait()
            session.status = SessionStatus.COMPLETED
            session.result = "done"
            session._client = None
            if mgr._on_complete:
                await mgr._on_complete(session)

        mgr._run_session = mock_run

        with patch("loom.orchestrator.session.ClaudeSDKClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.connect = AsyncMock()
            mock_cls.return_value = mock_client

            # Spawn 4 sessions with max_concurrent=2
            for i in range(4):
                await mgr.spawn(envelope_id=f"env-{i}", task_prompt=f"prompt {i}")

            # Give tasks a moment to start
            await asyncio.sleep(0.1)

            # Only 2 should have started (semaphore limits)
            assert len(started) == 2

            # Finish first batch
            finish_events[0].set()
            finish_events[1].set()
            await asyncio.sleep(0.1)

            # Next 2 should have started
            assert len(started) == 4
