"""Claude Code session manager — powered by claude-agent-sdk.

Uses ``ClaudeSDKClient`` for bidirectional, stateful sessions and ``query()``
for simple one-shot tasks.  Each Session wraps a ``ClaudeSDKClient`` instance
and exposes lifecycle helpers (spawn, cancel, send follow-up, collect results).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

logger = logging.getLogger(__name__)


class SessionStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentStep:
    """A single step in the agent's processing log."""
    step: str
    input: str = ""
    output: str = ""
    timestamp: str = ""


@dataclass
class Session:
    """Represents a managed Claude Code session backed by ClaudeSDKClient."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: SessionStatus = SessionStatus.IDLE
    envelope_id: str = ""
    prompt_template: str = ""
    system_prompt: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: str = ""
    error: str = ""
    steps: list[AgentStep] = field(default_factory=list)
    total_cost_usd: float = 0.0
    _client: ClaudeSDKClient | None = field(default=None, repr=False)


class SessionManager:
    """Manages Claude Code session lifecycle via claude-agent-sdk.

    Two modes:
    - **Interactive** — persistent ``ClaudeSDKClient`` for multi-turn conversations
      (user follow-ups, interrupts, model switching).
    - **One-shot** — ``query()`` for fire-and-forget tasks (RSS summary, etc.).

    Enforces concurrency limits and collects results (summary text, tool usage,
    cost) into the Session record for the Web UI to display.
    """

    def __init__(
        self,
        max_concurrent: int = 3,
        prompt_dir: Path | None = None,
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._max_concurrent = max_concurrent
        self._prompt_dir = prompt_dir or Path.home() / ".loom" / "prompts"
        self._templates: dict[str, str] = {}
        self._load_prompt_templates()

    def _load_prompt_templates(self) -> None:
        """Load prompt templates from ~/.loom/prompts/*.md."""
        if self._prompt_dir.exists():
            for path in sorted(self._prompt_dir.glob("*.md")):
                self._templates[path.stem] = path.read_text()

    def get_prompt_template(self, name: str) -> str:
        """Resolve a prompt template by name (e.g. 'prompt_github_critical_issue')."""
        return self._templates.get(name, name)

    @property
    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.status == SessionStatus.RUNNING)

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def list_sessions(self, status: SessionStatus | None = None) -> list[Session]:
        sessions = list(self._sessions.values())
        if status:
            sessions = [s for s in sessions if s.status == status]
        return sessions

    # ------------------------------------------------------------------
    # Interactive session (multi-turn via ClaudeSDKClient)
    # ------------------------------------------------------------------

    async def spawn(
        self,
        envelope_id: str,
        prompt_template: str,
        system_prompt: str = "",
        allowed_tools: list[str] | None = None,
        agent_name: str | None = None,
    ) -> Session:
        """Spawn a new interactive Claude Code session for the given envelope.

        Uses ``ClaudeSDKClient`` so the session supports:
        - Multi-turn follow-ups from the user
        - Interrupts (cancel mid-task)
        - Permission mode changes
        - Model switching
        """
        if self.active_count >= self._max_concurrent:
            logger.warning(
                "Max concurrent sessions (%d) reached — envelope %s queued",
                self._max_concurrent, envelope_id,
            )

        resolved_prompt = self.get_prompt_template(prompt_template)

        options = ClaudeAgentOptions(
            system_prompt=system_prompt or resolved_prompt,
            allowed_tools=allowed_tools or [],
        )

        session = Session(
            envelope_id=envelope_id,
            prompt_template=prompt_template,
            system_prompt=system_prompt or resolved_prompt,
            status=SessionStatus.RUNNING,
            started_at=datetime.utcnow(),
        )
        self._sessions[session.id] = session

        client = ClaudeSDKClient(options=options)
        session._client = client

        try:
            await client.connect()
        except Exception as exc:
            session.status = SessionStatus.FAILED
            session.error = str(exc)
            logger.error("Failed to connect session %s: %s", session.id, exc)
            return session

        # Build the task prompt from the envelope context
        task_prompt = resolved_prompt if not system_prompt else resolved_prompt

        # Fire off the initial query — collect results in background
        import asyncio
        asyncio.create_task(self._run_session(session, task_prompt))

        return session

    async def _run_session(self, session: Session, prompt: str) -> None:
        """Background task: send prompt to client and collect results."""
        client = session._client
        if client is None:
            session.status = SessionStatus.FAILED
            session.error = "No client attached"
            return

        try:
            await client.query(prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            session.steps.append(AgentStep(
                                step="assistant",
                                output=block.text,
                                timestamp=datetime.utcnow().isoformat(),
                            ))
                        elif isinstance(block, ToolUseBlock):
                            session.steps.append(AgentStep(
                                step=f"tool:{block.name}",
                                input=str(block.input),
                                timestamp=datetime.utcnow().isoformat(),
                            ))

                elif isinstance(message, ResultMessage):
                    session.result = "\n".join(
                        s.output for s in session.steps if s.step == "assistant"
                    )
                    if message.total_cost_usd:
                        session.total_cost_usd = message.total_cost_usd

            session.status = SessionStatus.COMPLETED
            session.completed_at = datetime.utcnow()

        except Exception as exc:
            session.status = SessionStatus.FAILED
            session.error = str(exc)
            logger.error("Session %s failed: %s", session.id, exc)

        finally:
            await client.disconnect()
            session._client = None

    # ------------------------------------------------------------------
    # Follow-up on an existing interactive session
    # ------------------------------------------------------------------

    async def follow_up(self, session_id: str, message: str) -> bool:
        """Send a follow-up message to a running interactive session."""
        session = self._sessions.get(session_id)
        if session is None or session._client is None:
            return False
        try:
            await session._client.query(message)
            # Re-run the response collector
            import asyncio
            asyncio.create_task(self._run_session(session, ""))
            return True
        except Exception as exc:
            logger.error("Follow-up failed for session %s: %s", session_id, exc)
            return False

    # ------------------------------------------------------------------
    # Cancel / interrupt
    # ------------------------------------------------------------------

    async def cancel(self, session_id: str) -> None:
        """Interrupt a running session gracefully."""
        session = self._sessions.get(session_id)
        if session is None:
            return
        if session._client is not None:
            try:
                await session._client.interrupt()
                await session._client.disconnect()
            except Exception:
                pass
            session._client = None
        session.status = SessionStatus.FAILED
        session.error = "Cancelled by user"

    # ------------------------------------------------------------------
    # One-shot query (fire-and-forget, no persistent client)
    # ------------------------------------------------------------------

    async def query_once(
        self,
        prompt: str,
        system_prompt: str = "",
        allowed_tools: list[str] | None = None,
    ) -> str:
        """Run a one-shot ``query()`` and return the assistant text.

        Suitable for background tasks like RSS summarisation where no
        multi-turn interaction is needed.
        """
        from claude_agent_sdk import query as sdk_query

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            allowed_tools=allowed_tools or [],
            max_turns=3,
        )

        texts: list[str] = []
        async for message in sdk_query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        texts.append(block.text)

        return "\n".join(texts)
