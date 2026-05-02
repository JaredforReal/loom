"""YAML-based policy engine for routing and filtering.

Policy rules map incoming envelopes to agent configurations including
``ClaudeAgentOptions``, ``AgentDefinition``, and prompt templates.

Example policy file::

    rules:
      - name: "Critical GitHub issues"
        match:
          source: github
          labels: ["bug", "P0"]
        action:
          priority: 3
          agent: "code-reviewer"        # maps to AgentDefinition
          prompt: "prompt_github_critical_issue"
          auto_approve: false
          tools: ["Read", "Grep", "Bash"]

      - name: "RSS digest"
        match:
          source: rss
        action:
          priority: 0
          prompt: "prompt_rss_summary"
          batch: true
          batch_window: 6h
          max_turns: 3
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class PolicyAction:
    """What to do when a rule matches."""

    priority: int = 1
    agent: str = ""  # AgentDefinition name (optional)
    prompt: str = ""  # Prompt template name or inline text
    auto_approve: bool = False
    batch: bool = False
    batch_window: str = ""  # e.g. "6h", "1d"
    tools: list[str] = field(default_factory=list)  # allowed_tools override
    max_turns: int | None = None  # limit agent turns
    system_prompt: str = ""  # Override system prompt
    model: str = ""  # e.g. "sonnet", "opus"
    skills: list[str] = field(default_factory=list)  # SDK skill names to inject
    cwd: str = ""  # Working directory for the agent session


@dataclass
class PolicyRule:
    """A single routing rule."""

    name: str = ""
    match: dict = field(default_factory=dict)
    action: PolicyAction = field(default_factory=PolicyAction)


class PolicyEngine:
    """Loads YAML policy files and evaluates envelopes against rules."""

    def __init__(self, policy_dir: Path | None = None, bundled_dir: Path | None = None) -> None:
        self._rules: list[PolicyRule] = []
        self._policy_dir: Path | None = policy_dir
        self._bundled_dir: Path | None = bundled_dir
        if policy_dir:
            self.load_policies(policy_dir, bundled_dir)

    @property
    def policy_dir(self) -> Path | None:
        return self._policy_dir

    @property
    def bundled_dir(self) -> Path | None:
        return self._bundled_dir

    def reload(self) -> None:
        """Reload from the originally configured directories."""
        if self._policy_dir is None:
            return
        self.load_policies(self._policy_dir, self._bundled_dir)

    def load_policies(self, policy_dir: Path, bundled_dir: Path | None = None) -> None:
        """Load policies: bundled defaults first, then user overrides.

        User rules are prepended so they match before bundled defaults.
        """
        self._policy_dir = policy_dir
        self._bundled_dir = bundled_dir
        self._rules.clear()

        bundled_rules: list[PolicyRule] = []
        if bundled_dir and bundled_dir.exists():
            for path in sorted(bundled_dir.glob("*.yaml")):
                self._load_file_into(path, bundled_rules)

        user_rules: list[PolicyRule] = []
        for path in sorted(policy_dir.glob("*.yaml")):
            self._load_file_into(path, user_rules)

        # User rules match first
        self._rules = user_rules + bundled_rules
        logger.info(
            "Loaded %d policy rules (%d user, %d bundled)",
            len(self._rules),
            len(user_rules),
            len(bundled_rules),
        )

    def _load_file_into(self, path: Path, target: list[PolicyRule]) -> None:
        with open(path) as f:
            data = yaml.safe_load(f)
        for rule_data in data.get("rules", []):
            action_data = rule_data.get("action", {})
            action = PolicyAction(
                priority=action_data.get("priority", 1),
                agent=action_data.get("agent", ""),
                prompt=action_data.get("prompt", action_data.get("agent_prompt", "")),
                auto_approve=action_data.get("auto_approve", False),
                batch=action_data.get("batch", False),
                batch_window=action_data.get("batch_window", ""),
                tools=action_data.get("tools", []),
                max_turns=action_data.get("max_turns"),
                system_prompt=action_data.get("system_prompt", ""),
                model=action_data.get("model", ""),
                skills=action_data.get("skills", []),
                cwd=action_data.get("cwd", ""),
            )
            target.append(
                PolicyRule(
                    name=rule_data.get("name", ""),
                    match=rule_data.get("match", {}),
                    action=action,
                )
            )

    def load_action_by_name(self, name: str, policy_dir: Path) -> PolicyAction | None:
        """Load a flat policy file (action fields only, no rules wrapper) by name."""
        path = policy_dir / f"{name}.yaml"
        if not path.exists():
            return None
        with open(path) as f:
            data = yaml.safe_load(f)
        if not data or not isinstance(data, dict):
            return None
        return PolicyAction(
            priority=data.get("priority", 1),
            agent=data.get("agent", ""),
            prompt=data.get("prompt", ""),
            auto_approve=data.get("auto_approve", False),
            batch=data.get("batch", False),
            batch_window=data.get("batch_window", ""),
            tools=data.get("tools", []),
            max_turns=data.get("max_turns"),
            system_prompt=data.get("system_prompt", ""),
            model=data.get("model", ""),
            skills=data.get("skills", []),
            cwd=data.get("cwd", ""),
        )

    def evaluate(self, envelope) -> PolicyAction | None:
        """Return the first matching rule's action, or None."""
        for rule in self._rules:
            if self._matches(rule, envelope):
                return rule.action
        return None

    def list_rules(self) -> list[dict[str, Any]]:
        """Return parsed rules as plain dicts (for API consumers)."""
        return [{"name": r.name, "match": r.match, "action": asdict(r.action)} for r in self._rules]

    def _matches(self, rule: PolicyRule, envelope) -> bool:
        match = rule.match
        if "group" in match and envelope.group != match["group"]:
            return False
        if "source" in match and envelope.source != match["source"]:
            return False
        if "labels" in match:
            if not all(lbl in envelope.labels for lbl in match["labels"]):
                return False
        if "source_id_pattern" in match:
            import re

            if not re.search(match["source_id_pattern"], envelope.source_id):
                return False
        if "title_pattern" in match:
            import re

            if not re.search(match["title_pattern"], envelope.title, re.IGNORECASE):
                return False
        return True
