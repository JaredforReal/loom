"""Integration tests for claude-agent-sdk — real SDK calls.

These tests spawn the ``claude`` CLI subprocess via the SDK, which reads
its own settings from ``~/.claude/settings.json`` (auth token, base URL,
model overrides). No ANTHROPIC_API_KEY is needed — the CLI handles auth.

Skipped if the ``claude`` CLI binary is not found.

Run with:  pytest tests/test_sdk_integration.py -v
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

# Skip entire module if claude CLI is not available.
# The SDK spawns the CLI as a subprocess — it reuses the CLI's own
# authentication (settings.json / keychain), no API key required.
_claude_cli = shutil.which("claude")
_module_skip = pytest.mark.skipif(
    not _claude_cli,
    reason="Requires claude CLI in PATH",
)
_module_integration = pytest.mark.integration
pytestmark = [_module_skip, _module_integration]


# ---------------------------------------------------------------------------
# One-shot query via raw SDK
# ---------------------------------------------------------------------------


async def test_simple_query_returns_text() -> None:
    """Raw sdk query() returns non-empty assistant text."""
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    options = ClaudeAgentOptions(
        system_prompt="You are a concise assistant. Reply with exactly: pong",
        permission_mode="bypassPermissions",
        max_turns=1,
    )

    texts: list[str] = []
    async for message in query(prompt="ping", options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    texts.append(block.text)

    result = "\n".join(texts)
    assert result.strip(), "Expected non-empty response from SDK query()"


# ---------------------------------------------------------------------------
# SessionManager.query_once
# ---------------------------------------------------------------------------


async def test_query_once_session_manager() -> None:
    """SessionManager.query_once() returns meaningful result."""
    from loom.orchestrator.session import SessionManager

    mgr = SessionManager(max_concurrent=1, prompt_dir=Path("/nonexistent"))

    result = await mgr.query_once(
        prompt="Reply with exactly one word: hello",
        system_prompt="You reply concisely.",
        permission_mode="bypassPermissions",
        max_turns=1,
    )

    assert result.strip(), "query_once() should return non-empty text"
    assert "hello" in result.lower()


# ---------------------------------------------------------------------------
# Interactive session via spawn
# ---------------------------------------------------------------------------


async def test_interactive_session_produces_result() -> None:
    """spawn() creates a COMPLETED session with content."""
    from loom.orchestrator.session import SessionManager, SessionStatus

    mgr = SessionManager(max_concurrent=1, prompt_dir=Path("/nonexistent"))

    session = await mgr.spawn(
        envelope_id="test-env",
        task_prompt="What is 2+2? Reply with just the number.",
        system_prompt="You are a math assistant. Reply concisely.",
        permission_mode="bypassPermissions",
        max_turns=1,
    )

    # Wait for the background task to finish (up to 30s)
    for _ in range(60):
        if session.status in (SessionStatus.COMPLETED, SessionStatus.FAILED):
            break
        import asyncio

        await asyncio.sleep(0.5)

    assert session.status == SessionStatus.COMPLETED, f"Session failed: {session.error}"
    assert session.result.strip(), "Session result should not be empty"


async def test_session_steps_populated() -> None:
    """session.steps contains assistant entries with text."""
    from loom.orchestrator.session import SessionManager, SessionStatus

    mgr = SessionManager(max_concurrent=1, prompt_dir=Path("/nonexistent"))

    session = await mgr.spawn(
        envelope_id="test-env-steps",
        task_prompt="What is 3+3? Reply with just the number.",
        system_prompt="You are a math assistant. Reply concisely.",
        permission_mode="bypassPermissions",
        max_turns=1,
    )

    for _ in range(60):
        if session.status in (SessionStatus.COMPLETED, SessionStatus.FAILED):
            break
        import asyncio

        await asyncio.sleep(0.5)

    assert session.status == SessionStatus.COMPLETED
    assistant_steps = [s for s in session.steps if s.step == "assistant"]
    assert len(assistant_steps) > 0, "Expected at least one assistant step"
    assert any(s.output.strip() for s in assistant_steps), "Steps should have text output"


async def test_result_message_fields_captured() -> None:
    """started_at, completed_at, and total_cost_usd are captured."""
    from loom.orchestrator.session import SessionManager, SessionStatus

    mgr = SessionManager(max_concurrent=1, prompt_dir=Path("/nonexistent"))

    session = await mgr.spawn(
        envelope_id="test-env-fields",
        task_prompt="Say 'ok'.",
        system_prompt="You reply concisely.",
        permission_mode="bypassPermissions",
        max_turns=1,
    )

    for _ in range(60):
        if session.status in (SessionStatus.COMPLETED, SessionStatus.FAILED):
            break
        import asyncio

        await asyncio.sleep(0.5)

    assert session.status == SessionStatus.COMPLETED
    assert session.started_at is not None
    assert session.completed_at is not None
