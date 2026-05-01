"""Dispatcher — routes envelopes to agent sessions via policy rules.

Subscribes to the event bus, evaluates incoming envelopes against the
policy engine, and spawns Claude Code sessions (via claude-agent-sdk)
to process them.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions

from loom.core.envelope import Envelope, EnvelopeStatus
from loom.core.eventbus import EventBus
from loom.orchestrator.policy import PolicyAction, PolicyEngine
from loom.orchestrator.session import SessionManager

if TYPE_CHECKING:
    from loom.core.mailbox import Mailbox

logger = logging.getLogger(__name__)


class Dispatcher:
    """Subscribes to the event bus and dispatches envelopes to agent sessions.

    Flow:
    1. Listen for ``new_envelope`` events
    2. Evaluate the envelope against policy rules
    3. If a rule matches, build ``ClaudeAgentOptions`` from the policy action
    4. Spawn an interactive or one-shot session via SessionManager
    5. Update envelope status and collect agent results
    """

    def __init__(
        self,
        bus: EventBus,
        session_mgr: SessionManager,
        policy_engine: PolicyEngine,
        mailbox: Mailbox,
    ) -> None:
        self._bus = bus
        self._sessions = session_mgr
        self._policy = policy_engine
        self._mailbox = mailbox

    async def start(self) -> None:
        """Subscribe to event bus."""
        self._bus.subscribe("new_envelope", self._on_new_envelope)

    async def stop(self) -> None:
        self._bus.unsubscribe("new_envelope", self._on_new_envelope)

    # ------------------------------------------------------------------
    # Event handler
    # ------------------------------------------------------------------

    async def _on_new_envelope(self, event: str, data) -> None:
        envelope: Envelope = data
        action = self._policy.evaluate(envelope)

        if action is None:
            logger.info("No matching policy rule for envelope %s — skipping", envelope.id)
            return

        # Update priority if policy overrides it
        if action.priority != envelope.priority:
            envelope.priority = action.priority

        await self._mailbox.update_status(envelope.id, EnvelopeStatus.PROCESSING)

        logger.info(
            "Dispatching envelope %s — agent=%s prompt=%s auto_approve=%s",
            envelope.id, action.agent, action.prompt, action.auto_approve,
        )

        # Decide: interactive (multi-turn) or one-shot
        if action.auto_approve:
            await self._dispatch_oneshot(envelope, action)
        else:
            await self._dispatch_interactive(envelope, action)

    # ------------------------------------------------------------------
    # Interactive dispatch (user review required)
    # ------------------------------------------------------------------

    async def _dispatch_interactive(self, envelope: Envelope, action: PolicyAction) -> None:
        """Spawn an interactive session whose results will be presented to the user."""
        system_prompt = action.system_prompt or self._build_system_prompt(envelope, action)

        session = await self._sessions.spawn(
            envelope_id=envelope.id,
            prompt_template=action.prompt,
            system_prompt=system_prompt,
            allowed_tools=action.tools or None,
            agent_name=action.agent or None,
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
            system_prompt=action.system_prompt or "You are a helpful assistant that processes messages.",
            allowed_tools=action.tools or None,
        )

        logger.info("One-shot result for envelope %s: %s", envelope.id, result[:200])

        # Store result on the envelope
        envelope.agent_summary = result
        envelope.proposed_action = {"auto_approved": True, "result": result}
        await self._mailbox.update_status(envelope.id, EnvelopeStatus.DONE)

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_system_prompt(self, envelope: Envelope, action: PolicyAction) -> str:
        """Build a system prompt that gives the agent context about the envelope."""
        return (
            "You are a personal agent that processes incoming messages on behalf of the user.\n"
            "Analyze the message, decide if action is needed, and propose a response.\n"
            f"Source: {envelope.source}\n"
            f"Title: {envelope.title}\n"
            "Do NOT take final action — present your analysis and recommendation for user approval."
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
        return prompt_template.format(
            source=envelope.source,
            title=envelope.title,
            body=envelope.body,
            source_id=envelope.source_id,
            labels=", ".join(envelope.labels),
        )
