# Loom

Loom is a mailbox and agent orchestration layer for Claude Code. It receives messages from external sources (GitHub, RSS, Gmail, Agent Network), dispatches them to Claude Code sessions for processing, and surfaces results to the user for final decision-making.

The core idea: **make passive LLM agents proactive** by turning external events into actionable agent tasks.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  External Sources                                                │
│  ┌────────┐ ┌─────┐ ┌───────┐ ┌──────┐                          │
│  │ GitHub │ │ RSS │ │ Gmail │ │ anet │  ...                      │
│  └───┬────┘ └──┬──┘ └───┬───┘ └──┬───┘                          │
│      │         │        │        │                               │
│      ▼         ▼        ▼        ▼                               │
│  ┌─────────────────────────────────────┐                         │
│  │            Adaptor Layer            │  Normalize → Envelope   │
│  └──────────────────┬──────────────────┘                         │
│                     ▼                                             │
│  ┌─────────────────────────────────────┐                         │
│  │            Mailbox (Core)           │  Receive, store, queue  │
│  └──────────────────┬──────────────────┘                         │
│                     ▼                                             │
│  ┌─────────────────────────────────────┐                         │
│  │         Event Bus (in-process)      │  Pub/Sub dispatch       │
│  └──────────────────┬──────────────────┘                         │
│                     ▼                                             │
│  ┌─────────────────────────────────────┐                         │
│  │       Orchestrator / Dispatcher     │  Envelope → Agent       │
│  │  ┌───────────────────────────────┐  │                         │
│  │  │   Policy Engine (YAML rules)  │  │  Route, filter, prompt  │
│  │  └───────────────────────────────┘  │                         │
│  └──────────────────┬──────────────────┘                         │
│                     ▼                                             │
│  ┌─────────────────────────────────────┐                         │
│  │     Claude Code Session Manager     │  Spawn / reuse sessions │
│  └──────────────────┬──────────────────┘                         │
│                     ▼                                             │
│  ┌─────────────────────────────────────┐                         │
│  │              Web UI                 │  Feed, detail, settings │
│  │  ┌──────┐ ┌──────┐ ┌────────────┐  │                         │
│  │  │ Feed │ │Detail│ │  Settings  │  │                         │
│  │  └──────┘ └──────┘ └────────────┘  │                         │
│  └─────────────────────────────────────┘                         │
│             ▲                                                    │
│             │  User approval / override                          │
└──────────────────────────────────────────────────────────────────┘
```

## Data Flow

1. **Ingest** — An adaptor (GitHub webhook, RSS poller, Gmail watcher, anet peer) receives an external event and normalizes it into an `Envelope`.
2. **Queue** — The Mailbox stores the envelope and publishes a `new_envelope` event to the internal event bus.
3. **Dispatch** — The Dispatcher subscribes to the event bus, applies policy rules to determine which agent session should handle the envelope, and spawns/reuses a Claude Code session.
4. **Process** — The agent session reads the envelope, executes the assigned prompt template, and produces a result (summary, action recommendation, draft reply, etc.).
5. **Review** — The result is surfaced in the Web UI. The user can approve, modify, or reject the agent's proposed action.
6. **Act** — On approval, Loom executes the action through the appropriate adaptor (reply to email, post comment, send anet message, etc.).

## Core Concepts

### Envelope

The universal message unit. Every external event is normalized into an envelope:

```python
@dataclass
class Envelope:
    id: str                  # UUID
    source: str              # "github", "rss", "gmail", "anet"
    source_id: str           # External ID (e.g. GitHub issue #42)
    title: str
    body: str                # Raw payload / HTML / markdown
    received_at: datetime
    status: EnvelopeStatus   # pending | processing | waiting_approval | done | dismissed
    priority: int            # 0=low, 1=normal, 2=high, 3=urgent
    labels: list[str]
    metadata: dict           # Source-specific fields
```

### Adaptor

A pluggable connector that knows how to interact with a specific external system. Responsibilities:

- **Subscribe** to the source (webhook, polling, IMAP, etc.)
- **Normalize** raw events into `Envelope` objects
- **Execute** approved actions back to the source

### Policy Rules

YAML-based routing and filtering rules. Example:

```yaml
rules:
  - name: "Critical GitHub issues"
    match:
      source: github
      labels: ["bug", "P0"]
    action:
      priority: 3
      agent: "code-reviewer"             # maps to AgentDefinition
      prompt: "prompt_github_critical_issue"
      tools: ["Read", "Grep", "Bash"]
      auto_approve: false

  - name: "RSS digest"
    match:
      source: rss
    action:
      priority: 0
      prompt: "prompt_rss_summary"
      batch: true
      batch_window: 6h
      max_turns: 3
      auto_approve: true
```

### Agent Session (powered by claude-agent-sdk)

Loom uses the [claude-agent-sdk](https://github.com/anthropics/claude-agent-sdk-python) to manage Claude Code sessions. Two modes:

- **Interactive** — Persistent `ClaudeSDKClient` sessions supporting multi-turn follow-ups, interrupts, permission mode changes, and model switching. Used when user review is required.
- **One-shot** — `query()` for fire-and-forget tasks (auto-approved actions like RSS summaries).

The session manager:

- Spawns sessions with `ClaudeAgentOptions` (system prompt, allowed tools, agent definitions)
- Tracks lifecycle (idle → running → completed / failed) and collects processing logs
- Supports follow-up messages and graceful interrupts via the SDK
- Enforces concurrency limits
- Records cost per session (`total_cost_usd` from `ResultMessage`)

## Project Structure

```
loom/
├── core/                   # Core mailbox engine
│   ├── envelope.py         #   Envelope data model
│   ├── mailbox.py          #   Mailbox: receive, store, query
│   └── eventbus.py         #   In-process async event bus
├── adaptor/                # External source adapters
│   ├── base.py             #   BaseAdaptor ABC
│   ├── github.py           #   GitHub (webhooks, issues, PRs)
│   ├── rss.py              #   RSS/Atom feed poller
│   ├── gmail.py            #   Gmail (IMAP/Google API)
│   └── anet.py             #   Agent Network peer
├── orchestrator/           # Agent coordination (claude-agent-sdk)
│   ├── session.py          #   Claude Code session manager (ClaudeSDKClient)
│   ├── dispatcher.py       #   Envelope → agent dispatch
│   └── policy.py           #   YAML policy engine → ClaudeAgentOptions
├── state/                  # Persistence layer
│   └── store.py            #   SQLite-backed state store
├── observability/          # Monitoring & metrics
│   └── metrics.py          #   Daemon status, queue depth, session count
├── cli/                    # CLI entry point
│   └── main.py             #   `loom` command
└── webui/                  # Web interface
    └── app.py              #   FastAPI + static SPA
```

## Quick Start

```bash
# Install (dev mode)
pip install -e ".[dev]"

# Start the daemon
loom daemon start

# Add a source
loom source add github --repo owner/repo --events issues,pull_requests
loom source add rss --url https://example.com/feed.xml
loom source add gmail --credentials ~/.loom/gmail-credentials.json

# Check status
loom status

# Open the web UI
loom ui
```

## Configuration

Loom stores configuration in `~/.loom/`:

```
~/.loom/
├── config.yaml          # General settings
├── policies/            # Policy rule files (*.yaml)
├── prompts/             # Prompt templates (*.md)
├── credentials/         # Encrypted adaptor credentials
└── data/
    └── loom.db          # SQLite state store
```

## Web UI

Three-panel layout:

| Left Panel | Center Panel | Right Panel |
|---|---|---|
| Source nav with unread counts | Feed cards (chronological, desc) | Detail drawer |
| GitHub (3) | [github] Fix login bug — **waiting** | Raw payload |
| RSS (12) | [rss] New release v2.0 — **done** | Agent processing log |
| Gmail (1) | [gmail] Meeting invite — **pending** | Approval buttons |
| anet | ... | |

Top status bar: daemon status | active sessions | queue backlog

Settings page: Policy editor (YAML) | Source subscriptions | Prompt templates

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
make test

# Run linter
make lint

# Start dev server (daemon + web UI with hot reload)
make dev
```

## License

MIT
