"""Claude Code session manager — powered by claude-agent-sdk.

Uses ``ClaudeSDKClient`` for bidirectional, stateful sessions and ``query()``
for simple one-shot tasks.  Each Session wraps a ``ClaudeSDKClient`` instance
and exposes lifecycle helpers (spawn, cancel, send follow-up, collect results).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

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
    cli_session_id: str = ""
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
        bundled_prompt_dir: Path | None = None,
        on_complete: Callable[[Session], Awaitable[None]] | None = None,
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._prompt_dir = prompt_dir or Path.home() / ".loom" / "prompts"
        self._bundled_prompt_dir = bundled_prompt_dir
        self._on_complete = on_complete
        self._templates: dict[str, str] = {}
        self._load_prompt_templates()

    def _load_prompt_templates(self) -> None:
        """Load prompt templates: bundled defaults -> user overrides -> per-source."""
        self._templates.clear()

        # Layer 1: Bundled defaults from the package
        if self._bundled_prompt_dir and self._bundled_prompt_dir.exists():
            for path in sorted(self._bundled_prompt_dir.glob("*.md")):
                self._templates[path.stem] = path.read_text()

        # Layer 2: User overrides from ~/.loom/prompts/*.md
        if self._prompt_dir.exists():
            for path in sorted(self._prompt_dir.glob("*.md")):
                self._templates[path.stem] = path.read_text()

        # Layer 3: Per-source overrides from ~/.loom/prompts/<source>/*.md
        # Namespaced as "github/acme-app" to avoid collisions
        if self._prompt_dir.exists():
            for source_dir in sorted(self._prompt_dir.iterdir()):
                if source_dir.is_dir():
                    for path in sorted(source_dir.glob("*.md")):
                        self._templates[f"{source_dir.name}/{path.stem}"] = path.read_text()

        logger.info("Loaded %d prompt templates", len(self._templates))

    def reload_prompts(self) -> None:
        """Re-read all prompt template files into the in-memory cache."""
        self._load_prompt_templates()

    @property
    def prompt_dir(self) -> Path:
        return self._prompt_dir

    @property
    def bundled_prompt_dir(self) -> Path | None:
        return self._bundled_prompt_dir

    def list_template_names(self) -> list[str]:
        """Return all loaded template names (for API consumers)."""
        return sorted(self._templates.keys())

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
        task_prompt: str,
        system_prompt: str = "",
        allowed_tools: list[str] | None = None,
        agent_name: str | None = None,
        model: str | None = None,
        max_turns: int | None = None,
        skills: list[str] | None = None,
        cwd: str | None = None,
        permission_mode: str | None = None,
    ) -> Session:
        """Spawn a new interactive Claude Code session for the given envelope.

        Respects ``max_concurrent`` via semaphore — waits for a slot if full.
        """
        effective_system_prompt = system_prompt or (
            "You are a personal agent that preprocesses incoming messages for the user.\n"
            "Your job is to summarize, classify urgency, and recommend what the user should do.\n"
            "Never execute actions directly. Always present your analysis for user approval."
        )

        effective_permission_mode = permission_mode or "bypassPermissions"

        options = ClaudeAgentOptions(
            system_prompt=effective_system_prompt,
            allowed_tools=allowed_tools or [],
            model=model,
            max_turns=max_turns,
            skills=skills,
            cwd=cwd,
            permission_mode=effective_permission_mode,
        )

        session = Session(
            envelope_id=envelope_id,
            prompt_template=task_prompt[:200],
            system_prompt=effective_system_prompt,
            status=SessionStatus.RUNNING,
            started_at=datetime.utcnow(),
        )
        self._sessions[session.id] = session

        # Acquire semaphore before connecting — blocks if at capacity
        async def _guarded_run() -> None:
            async with self._semaphore:
                client = ClaudeSDKClient(options=options)
                session._client = client
                try:
                    await client.connect()
                except Exception as exc:
                    session.status = SessionStatus.FAILED
                    session.error = str(exc)
                    logger.error("Failed to connect session %s: %s", session.id, exc)
                    return
                await self._run_session(session, task_prompt)

        asyncio.create_task(_guarded_run())
        return session

    async def _run_session(self, session: Session, prompt: str) -> None:
        """Background task: send prompt to client and collect results."""
        client = session._client
        if client is None:
            session.status = SessionStatus.FAILED
            session.error = "No client attached"
            if self._on_complete:
                try:
                    await self._on_complete(session)
                except Exception:
                    logger.exception("on_complete callback failed for session %s", session.id)
            return

        try:
            await client.query(prompt)

            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            session.steps.append(
                                AgentStep(
                                    step="assistant",
                                    output=block.text,
                                    timestamp=datetime.utcnow().isoformat(),
                                )
                            )
                        elif isinstance(block, ToolUseBlock):
                            session.steps.append(
                                AgentStep(
                                    step=f"tool:{block.name}",
                                    input=str(block.input),
                                    timestamp=datetime.utcnow().isoformat(),
                                )
                            )

                elif isinstance(message, ResultMessage):
                    if message.session_id:
                        session.cli_session_id = message.session_id
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
            if self._on_complete:
                try:
                    await self._on_complete(session)
                except Exception:
                    logger.exception("on_complete callback failed for session %s", session.id)

    # ------------------------------------------------------------------
    # Follow-up on an existing interactive session
    # ------------------------------------------------------------------

    async def follow_up(self, session_id: str, message: str) -> bool:
        """Send a follow-up message to a running interactive session."""
        session = self._sessions.get(session_id)
        if session is None or session._client is None:
            return False
        client = session._client
        try:
            await client.query(message)

            # Collect response inline — do NOT delegate to _run_session
            # which would re-send an empty query.
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            session.steps.append(
                                AgentStep(
                                    step="assistant",
                                    output=block.text,
                                    timestamp=datetime.utcnow().isoformat(),
                                )
                            )
                        elif isinstance(block, ToolUseBlock):
                            session.steps.append(
                                AgentStep(
                                    step=f"tool:{block.name}",
                                    input=str(block.input),
                                    timestamp=datetime.utcnow().isoformat(),
                                )
                            )
                elif isinstance(msg, ResultMessage):
                    if msg.session_id:
                        session.cli_session_id = msg.session_id
                    session.result = "\n".join(
                        s.output for s in session.steps if s.step == "assistant"
                    )
                    if msg.total_cost_usd:
                        session.total_cost_usd = msg.total_cost_usd

            session.status = SessionStatus.COMPLETED
            session.completed_at = datetime.utcnow()
            return True
        except Exception as exc:
            logger.error("Follow-up failed for session %s: %s", session_id, exc)
            session.status = SessionStatus.FAILED
            session.error = str(exc)
            return False
        finally:
            if session._client is not None:
                await client.disconnect()
                session._client = None
            if self._on_complete:
                try:
                    await self._on_complete(session)
                except Exception:
                    logger.exception("on_complete callback failed for session %s", session.id)

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
        model: str | None = None,
        max_turns: int | None = None,
        skills: list[str] | None = None,
        cwd: str | None = None,
        permission_mode: str | None = None,
    ) -> str:
        """Run a one-shot ``query()`` and return the assistant text.

        Suitable for background tasks like RSS summarisation where no
        multi-turn interaction is needed.
        """
        from claude_agent_sdk import query as sdk_query

        effective_permission_mode = permission_mode or "bypassPermissions"

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            allowed_tools=allowed_tools or [],
            max_turns=max_turns or 3,
            model=model,
            skills=skills,
            cwd=cwd,
            permission_mode=effective_permission_mode,
        )

        texts: list[str] = []
        async for message in sdk_query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        texts.append(block.text)

        return "\n".join(texts)
