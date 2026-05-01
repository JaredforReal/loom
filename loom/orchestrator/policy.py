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

from dataclasses import dataclass, field
from pathlib import Path

import yaml


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


@dataclass
class PolicyRule:
    """A single routing rule."""

    name: str = ""
    match: dict = field(default_factory=dict)
    action: PolicyAction = field(default_factory=PolicyAction)


class PolicyEngine:
    """Loads YAML policy files and evaluates envelopes against rules."""

    def __init__(self, policy_dir: Path | None = None) -> None:
        self._rules: list[PolicyRule] = []
        if policy_dir:
            self.load_policies(policy_dir)

    def load_policies(self, policy_dir: Path) -> None:
        """Load all *.yaml files from the given directory."""
        self._rules.clear()
        for path in sorted(policy_dir.glob("*.yaml")):
            self._load_file(path)

    def _load_file(self, path: Path) -> None:
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
            )
            self._rules.append(
                PolicyRule(
                    name=rule_data.get("name", ""),
                    match=rule_data.get("match", {}),
                    action=action,
                )
            )

    def evaluate(self, envelope) -> PolicyAction | None:
        """Return the first matching rule's action, or None."""
        for rule in self._rules:
            if self._matches(rule, envelope):
                return rule.action
        return None

    def _matches(self, rule: PolicyRule, envelope) -> bool:
        match = rule.match
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
