"""Dispatcher — routes envelopes to agent sessions via policy rules.

Subscribes to the event bus, evaluates incoming envelopes against the
policy engine, and spawns Claude Code sessions (via claude-agent-sdk)
to process them.

Supports independent control of the agent processor:
- ``agent_enabled=True``: dispatch envelopes to agent sessions
- ``agent_enabled=False``: collect envelopes but skip processing
- ``drain_pending()``: process backlog of PENDING envelopes
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from loom.config import GroupConfig, LoomConfig
from loom.core.envelope import Envelope, EnvelopeStatus
from loom.core.eventbus import EventBus
from loom.orchestrator.policy import PolicyAction, PolicyEngine
from loom.orchestrator.session import Session, SessionManager, SessionStatus

if TYPE_CHECKING:
    from loom.core.mailbox import Mailbox

logger = logging.getLogger(__name__)


class _SafeDict(dict):
    """Dict that returns empty string for missing keys — safe for .format_map()."""

    def __missing__(self, key: str) -> str:
        return ""


class Dispatcher:
    """Subscribes to the event bus and dispatches envelopes to agent sessions.

    Two independent toggles:
    - **Mailbox** (adaptors): collects envelopes from external sources
    - **Agent** (processor): runs Claude Code sessions on collected envelopes

    Both can be on or off independently. When the agent is off, envelopes
    accumulate in PENDING status. ``drain_pending()`` processes the backlog.
    """

    def __init__(
        self,
        bus: EventBus,
        session_mgr: SessionManager,
        policy_engine: PolicyEngine,
        mailbox: Mailbox,
        agent_enabled: bool = True,
        config: LoomConfig | None = None,
    ) -> None:
        self._bus = bus
        self._sessions = session_mgr
        self._policy = policy_engine
        self._mailbox = mailbox
        self._agent_enabled = agent_enabled
        self._config = config
        self._drain_task: asyncio.Task | None = None

    @property
    def agent_enabled(self) -> bool:
        return self._agent_enabled

    def set_agent_enabled(self, enabled: bool) -> None:
        """Toggle agent processing on/off. Starts drain when enabled."""
        changed = self._agent_enabled != enabled
        self._agent_enabled = enabled
        if changed:
            state = "enabled" if enabled else "disabled"
            logger.info("Agent processing %s", state)
            if enabled:
                self._start_drain()

    async def start(self) -> None:
        """Subscribe to event bus."""
        self._bus.subscribe("new_envelope", self._on_new_envelope)

    async def stop(self) -> None:
        self._bus.unsubscribe("new_envelope", self._on_new_envelope)
        if self._drain_task:
            self._drain_task.cancel()
            try:
                await self._drain_task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    async def _on_new_envelope(self, event: str, data) -> None:
        envelope: Envelope = data

        if not self._agent_enabled:
            logger.debug("Agent disabled — envelope %s stays PENDING", envelope.id)
            return

        await self._try_dispatch(envelope)

    # ------------------------------------------------------------------
    # Dispatch core
    # ------------------------------------------------------------------

    async def _try_dispatch(self, envelope: Envelope) -> None:
        """Evaluate envelope against policy and dispatch if matched."""
        action = self._policy.evaluate(envelope)

        # Fallback: use group defaults if no policy rule matched
        if action is None and envelope.group and self._config:
            grp: GroupConfig | None = self._config.groups.get(envelope.group)
            if grp and (grp.prompt or grp.system_prompt or grp.auto_approve):
                action = PolicyAction(
                    prompt=grp.prompt,
                    system_prompt=grp.system_prompt,
                    skills=grp.skills,
                    tools=grp.tools,
                    model=grp.model,
                    max_turns=grp.max_turns,
                    auto_approve=grp.auto_approve,
                )

        if action is None:
            logger.info("No matching policy rule for envelope %s — skipping", envelope.id)
            return

        if action.priority != envelope.priority:
            envelope.priority = action.priority

        await self._mailbox.update_status(envelope.id, EnvelopeStatus.PROCESSING)

        logger.info(
            "Dispatching envelope %s — agent=%s prompt=%s auto_approve=%s",
            envelope.id,
            action.agent,
            action.prompt,
            action.auto_approve,
        )

        if action.auto_approve:
            await self._dispatch_oneshot(envelope, action)
        else:
            await self._dispatch_interactive(envelope, action)

    # ------------------------------------------------------------------
    # Pending drain
    # ------------------------------------------------------------------

    def _start_drain(self) -> None:
        """Start background task to process PENDING envelopes."""
        if self._drain_task and not self._drain_task.done():
            return
        self._drain_task = asyncio.create_task(self._drain_pending())

    async def drain_pending(self) -> int:
        """Process all PENDING envelopes. Returns count dispatched."""
        pending = await self._mailbox._store.query_envelopes(
            status=EnvelopeStatus.PENDING, limit=10_000
        )
        if not pending:
            return 0

        logger.info("Draining %d pending envelopes", len(pending))
        count = 0
        for env in pending:
            if not self._agent_enabled:
                break
            await self._try_dispatch(env)
            count += 1
        return count

    async def _drain_pending(self) -> None:
        """Background task that drains pending envelopes."""
        try:
            await self.drain_pending()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Error draining pending envelopes")

    # ------------------------------------------------------------------
    # Interactive dispatch (user review required)
    # ------------------------------------------------------------------

    async def _dispatch_interactive(self, envelope: Envelope, action: PolicyAction) -> None:
        """Spawn an interactive session whose results will be presented to the user."""
        system_prompt = action.system_prompt or self._build_system_prompt(envelope, action)
        task_prompt = self._build_task_prompt(envelope, action)

        session = await self._sessions.spawn(
            envelope_id=envelope.id,
            task_prompt=task_prompt,
            system_prompt=system_prompt,
            allowed_tools=action.tools or None,
            agent_name=action.agent or None,
            model=action.model or None,
            max_turns=action.max_turns,
            skills=action.skills or None,
            cwd=action.cwd or None,
            permission_mode="bypassPermissions",
        )
        logger.info("Interactive session %s spawned for envelope %s", session.id, envelope.id)

    # ------------------------------------------------------------------
    # One-shot dispatch (auto-approve, fire-and-forget)
    # ------------------------------------------------------------------

    async def _dispatch_oneshot(self, envelope: Envelope, action: PolicyAction) -> None:
        """Run a one-shot query, then auto-execute the result."""
        prompt = self._build_task_prompt(envelope, action)

        result = await self._sessions.query_once(
            prompt=prompt,
            system_prompt=action.system_prompt
            or "You are a helpful assistant that processes messages.",
            allowed_tools=action.tools or None,
            model=action.model or None,
            max_turns=action.max_turns,
            skills=action.skills or None,
            cwd=action.cwd or None,
            permission_mode="bypassPermissions",
        )

        logger.info("One-shot result for envelope %s: %s", envelope.id, result[:200])

        # Store result on the envelope
        envelope.agent_summary = result
        envelope.proposed_action = {"auto_approved": True, "result": result}
        await self._mailbox.save_and_transition(envelope, EnvelopeStatus.DONE)

    # ------------------------------------------------------------------

    def _build_system_prompt(self, envelope: Envelope, action: PolicyAction) -> str:
        """Build a system prompt that gives the agent context about its role."""
        return (
            "You are a personal agent that preprocesses incoming messages for "
            "the user.\n"
            "Your job is to help the user READ and UNDERSTAND their messages, "
            "not to take actions on their behalf.\n"
            "For each message: summarize, classify urgency, and recommend "
            "what the user should do.\n"
            "Never execute actions directly. Always present your analysis "
            "for the user to approve.\n"
            f"Current message source: {envelope.source}\n"
        )

    def _build_task_prompt(self, envelope: Envelope, action: PolicyAction) -> str:
        """Build the full task prompt for an envelope."""
        prompt_template = self._sessions.get_prompt_template(action.prompt)

        # If the template is just a name (not found), build a default prompt
        if prompt_template == action.prompt:
            return (
                f"Process this message from {envelope.source}:\n\n"
                f"Title: {envelope.title}\n\n"
                f"Content:\n{envelope.body}\n\n"
                "Summarize the key points and recommend any actions."
            )

        # Interpolate envelope fields into the template
        context = _SafeDict(
            {
                "source": envelope.source,
                "title": envelope.title,
                "body": envelope.body or "",
                "source_id": envelope.source_id,
                "labels": ", ".join(envelope.labels),
                "metadata": _SafeDict(envelope.metadata),
            }
        )
        return prompt_template.format_map(context)

    # ------------------------------------------------------------------
    # Session completion callback
    # ------------------------------------------------------------------

    async def handle_session_complete(self, session: Session) -> None:
        """Called by SessionManager when a background session finishes.

        Updates the associated envelope's status and agent output fields.
        """
        if not session.envelope_id:
            return

        envelope = await self._mailbox._store.get_envelope(session.envelope_id)
        if envelope is None:
            logger.warning(
                "Session %s completed but envelope %s not found", session.id, session.envelope_id
            )
            return

        if session.status == SessionStatus.COMPLETED:
            envelope.agent_summary = session.result
            envelope.agent_log = [
                {"step": s.step, "input": s.input, "output": s.output, "timestamp": s.timestamp}
                for s in session.steps
            ]
            await self._mailbox.save_and_transition(envelope, EnvelopeStatus.WAITING_APPROVAL)
            logger.info(
                "Envelope %s -> WAITING_APPROVAL (session %s completed)", envelope.id, session.id
            )

        elif session.status == SessionStatus.FAILED:
            envelope.agent_summary = f"Session failed: {session.error}"
            await self._mailbox.save_and_transition(envelope, EnvelopeStatus.FAILED)
            logger.error("Envelope %s -> FAILED (session %s)", envelope.id, session.id)
