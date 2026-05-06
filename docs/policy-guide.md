# Policy Guide

Policies control how Loom processes incoming envelopes. Each policy file contains rules that match envelopes and define how the agent should handle them.

## Quick Start

Policies live in `~/.loom/policies/*.yaml`. User policies override bundled defaults (in `loom/policies/`).

A minimal policy:

```yaml
rules:
  - name: "My GitHub rule"
    match:
      source: github
    action:
      priority: 1
      prompt: prompt_github_issue
      auto_approve: false
```

## How Rules Work

Rules are evaluated **first-match wins**, in this order:
1. User rules (all `~/.loom/policies/*.yaml` files, sorted alphabetically, rules in document order)
2. Bundled defaults (from `loom/policies/`)

If no rule matches, Loom checks if the envelope's group has a linked policy file (set in config under `groups`).

## Match Fields

All match fields are optional and combined with AND logic. An empty `match: {}` matches every envelope.

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | Exact match on envelope source: `github`, `gmail`, `rss`, `arxiv` |
| `group` | string | Exact match on the envelope's group name |
| `labels` | list[string] | **ALL** labels must be present on the envelope (subset check) |
| `source_id_pattern` | regex | Regex search on `source_id` (e.g. `vllm-project/vllm#`) |
| `title_pattern` | regex | Case-insensitive regex search on title |

### Match examples

Only GitHub issues from a specific repo:
```yaml
match:
  source: github
  source_id_pattern: "vllm-project/vllm#"
```

Items labeled both "bug" AND "P0":
```yaml
match:
  source: github
  labels: ["bug", "P0"]
```

Items from a specific group:
```yaml
match:
  group: "vllm-project/vllm"
```

## Action Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `priority` | int | `1` | Envelope priority: 0=low, 1=normal, 2=high, 3=urgent |
| `prompt` | string | `""` | Prompt template name (e.g. `prompt_github_issue`) or inline text |
| `model` | string | `""` | Agent model: `sonnet`, `opus`, `haiku` |
| `auto_approve` | bool | `false` | Run agent and execute the result without user review |
| `tools` | list[string] | `[]` | Allowed Claude Code tools (e.g. `Read`, `Grep`, `Bash`). Empty = all tools |
| `max_turns` | int/null | `null` | Limit agent conversation turns. `null` = unlimited |
| `cwd` | string | `""` | Working directory for the agent session |
| `system_prompt` | string | `""` | Override the agent's system prompt entirely |
| `batch` | bool | `false` | Group envelopes over a time window before processing |
| `batch_window` | string | `""` | Duration string (e.g. `6h`, `1d`). Only used when `batch: true` |
| `skills` | list[string] | `[]` | SDK skill names to inject into the agent session |
| `agent` | string | `""` | Agent definition name (reserved for future use) |

### Loom-specific concepts

**auto_approve** — When `true`, the agent runs a one-shot query and marks the envelope as done immediately. The user never sees an "In Review" state. Useful for low-priority items like promotional emails where you just want a summary filed automatically.

**batch / batch_window** — When `batch: true`, envelopes matching this rule are collected for the specified duration before being processed together. Designed for digest-style processing (e.g. batch all promotional emails over 6 hours into one summary).

**tools** — Restricts which Claude Code tools the agent can use. For example, setting `tools: [Read, Grep]` prevents the agent from running shell commands or writing files. Useful for read-only analysis tasks.

**cwd** — Sets the working directory for the Claude Code agent session. When set to a local repo clone, the agent can read files and understand the codebase context.

**prompt** — References a prompt template by name (e.g. `prompt_github_issue`). Templates are resolved from:
1. Per-source: `~/.loom/prompts/<source>/<name>.md`
2. User: `~/.loom/prompts/<name>.md`
3. Bundled: `loom/prompts/<name>.md`

Templates use Python format syntax: `{source}`, `{title}`, `{body}`, `{labels}`, `{source_id}`, `{metadata[user]}`, etc.

## Groups and Policies

Groups link sources to policies. In `~/.loom/config.yaml`:

```yaml
groups:
  "vllm-project/vllm": "vllm_policy"
```

When a source has `group: vllm-project/vllm`:
1. Policy rules with `match.group: vllm-project/vllm` match first
2. If no rule matches, Loom loads `~/.loom/policies/vllm_policy.yaml` as a flat action (no `rules:` wrapper)

## Full Example

```yaml
rules:
  # Critical bugs from any source — urgent, interactive review
  - name: "Critical bugs"
    match:
      labels: ["bug", "P0"]
    action:
      priority: 3
      prompt: prompt_github_issue
      model: sonnet
      max_turns: 5
      tools: [Read, Grep, WebFetch]
      auto_approve: false

  # vllm repo issues — use local clone for context
  - name: "vllm project issues"
    match:
      source: github
      source_id_pattern: "vllm-project/vllm#"
    action:
      priority: 2
      prompt: "github/vllm"
      model: sonnet
      max_turns: 5
      cwd: "~/projects/vllm"
      auto_approve: false

  # Promotional emails — auto-summarize, no review needed
  - name: "Promo digest"
    match:
      source: gmail
      labels: ["CATEGORY_PROMOTIONS"]
    action:
      priority: 0
      batch: true
      batch_window: "6h"
      auto_approve: true

  # Catch-all for RSS
  - name: "RSS items"
    match:
      source: rss
    action:
      priority: 1
      prompt: prompt_rss
      auto_approve: false
```
