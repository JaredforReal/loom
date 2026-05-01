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
│  │        (claude-agent-sdk)           │                         │
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

1. **Ingest** — An adaptor polls or subscribes to an external source and normalizes events into an `Envelope`.
2. **Queue** — The Mailbox persists the envelope via SQLite Store and publishes a `new_envelope` event to the event bus.
3. **Dispatch** — The Dispatcher subscribes to the event bus, applies policy rules, and spawns a Claude Code session.
4. **Process** — The agent session reads the envelope, executes the assigned prompt template, and produces a result.
5. **Review** — The result is surfaced in the Web UI. The user can approve, modify, or reject the proposed action.
6. **Act** — On approval, Loom executes the action through the originating adaptor (post comment, reply email, etc.).

## Core Concepts

### Envelope

The universal message unit. Every external event is normalized into an envelope:

```python
@dataclass
class Envelope:
    id: str                  # UUID
    source: str              # "github", "rss", "gmail", "anet"
    source_id: str           # External ID (e.g. "acme/app#42")
    title: str
    body: str                # Raw payload / HTML / markdown
    received_at: datetime
    status: EnvelopeStatus   # pending → processing → waiting_approval → done | dismissed | failed
    priority: int            # 0=low, 1=normal, 2=high, 3=urgent
    labels: list[str]
    metadata: dict           # Source-specific fields
    agent_summary: str       # Filled by agent after processing
    proposed_action: dict    # Action awaiting user approval
```

### Adaptor

A pluggable connector that interacts with a specific external system:

- **Subscribe** to the source (polling, webhook, etc.)
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
      agent: "code-reviewer"
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
      auto_approve: true
```

### Agent Session (claude-agent-sdk)

Loom uses the [claude-agent-sdk](https://github.com/anthropics/claude-agent-sdk-python) to manage Claude Code sessions. Two modes:

- **Interactive** — Persistent `ClaudeSDKClient` sessions for multi-turn follow-ups. Used when user review is required.
- **One-shot** — `query()` for fire-and-forget tasks (auto-approved actions like RSS summaries).

## Project Structure

```
loom/
├── config.py                # Config loading/saving (~/.loom/config.yaml)
├── core/                    # Core mailbox engine
│   ├── envelope.py          #   Envelope data model + EnvelopeStatus enum
│   ├── eventbus.py          #   In-process async pub/sub
│   └── mailbox.py           #   Mailbox: receive → store → publish
├── adaptor/                 # External source adapters
│   ├── base.py              #   BaseAdaptor ABC (start/stop/normalize/execute_action)
│   ├── github.py            #   GitHub REST API polling (issues + PRs)
│   ├── gmail.py             #   Gmail OAuth2 + Google API polling
│   ├── rss.py               #   RSS/Atom feed poller (stub)
│   └── anet.py              #   Agent Network peer (stub)
├── orchestrator/            # Agent coordination (claude-agent-sdk)
│   ├── session.py           #   Claude Code session manager
│   ├── dispatcher.py        #   Envelope → agent dispatch + policy evaluation
│   └── policy.py            #   YAML policy engine
├── state/                   # Persistence layer
│   └── store.py             #   SQLite store (SQLAlchemy + aiosqlite)
├── observability/           # Monitoring & metrics
│   └── metrics.py           #   Daemon status, session count
├── cli/                     # CLI entry point
│   └── main.py              #   `loom` argparse parser + commands
├── webui/                   # Web interface
│   └── app.py               #   FastAPI REST API
├── policies/                # Default policy files
│   └── github.yaml          #   GitHub routing rules
└── prompts/                 # Default prompt templates
    └── prompt_github_issue.md
```

## Quick Start

```bash
# Clone and install (dev mode)
git clone https://github.com/user/loom.git
cd loom
pip install -e ".[dev]"

# For Gmail support
pip install -e ".[gmail]"

# Configure sources
loom source add github --repo owner/repo --events issues,pull_requests
loom source add gmail --credentials ~/.loom/credentials/gmail-client-secrets.json
loom source list

# Start the daemon
loom daemon
```

## Configuration

Loom stores all state in `~/.loom/`:

```
~/.loom/
├── config.yaml          # Daemon settings + source subscriptions
├── policies/            # Policy rule files (*.yaml)
├── prompts/             # Prompt templates (*.md)
├── credentials/         # OAuth tokens, API keys
└── data/
    └── loom.db          # SQLite state (envelopes + adaptor state)
```

### config.yaml

```yaml
daemon:
  host: "127.0.0.1"
  port: 8732

agent:
  max_concurrent: 3
  model: "sonnet"

sources:
  - kind: github
    owner: "acme"
    repo: "app"
    poll_interval: 120
    events: ["issues", "pull_requests"]
    state: "all"

  - kind: gmail
    client_secrets: "~/.loom/credentials/gmail-client-secrets.json"
    query: "is:unread -in:chats newer_than:1d"
    poll_seconds: 30

paths:
  policies_dir: "~/.loom/policies"
  prompts_dir: "~/.loom/prompts"
  data_dir: "~/.loom/data"
  credentials_dir: "~/.loom/credentials"
```

### Environment Variables

| Variable | Purpose |
|---|---|
| `GITHUB_TOKEN` | GitHub personal access token for the GitHub adaptor |

## Adaptors

### GitHub (REST API Polling)

Polls `GET /repos/{owner}/{repo}/issues?since={cursor}` for incremental updates. No public endpoint or webhook required — designed for local dev machines.

Features:
- `since` cursor for incremental updates
- ETag / `If-None-Match` conditional requests (304 support)
- Rate limit handling with `X-RateLimit-Reset` backoff
- Per-repo polling interval (default 120s)
- Event type filter (issues, pull_requests, or both)
- Label filter
- Cursor persistence across restarts

Actions: `comment`, `close`, `label` (add/remove)

### Gmail (Google API + OAuth2)

Polls Gmail via the Google API with OAuth2 browser-based auth flow on first use. Token cached locally and refreshed automatically.

Features:
- Configurable Gmail query string (default: `is:unread -in:chats newer_than:1d`)
- APScheduler polling (default 30s)
- Full MIME body decoding (text/plain preferred, HTML fallback, multipart walking)
- Thread-aware header extraction (Message-ID, In-Reply-To, References)
- Seen-set persistence (bounded deque, max 1000)
- Proxy support (HTTP, SOCKS4, SOCKS5)

Actions: `reply` (with threading headers), `archive`, `label`, `trash`

## CLI Reference

```
loom daemon                    Start the daemon (mailbox + dispatcher + web UI)
loom status                    Show daemon status
loom source add <kind>         Add a source subscription
loom source list               List configured sources
loom ui                        Open the web UI
```

### `loom source add github`

```
loom source add github --repo owner/repo [--repo owner/repo2 ...]
    --events issues,pull_requests   # Event types (default: both)
    --interval 120                  # Poll interval in seconds
    --state all                     # open, closed, or all
    --token <token>                 # Or set GITHUB_TOKEN env
```

### `loom source add gmail`

```
loom source add gmail --credentials ~/.loom/credentials/gmail-client-secrets.json
```

## Web UI

Three-panel layout:

| Left Panel | Center Panel | Right Panel |
|---|---|---|
| Source nav with unread counts | Feed cards (chronological, desc) | Detail drawer |
| GitHub (3) | [github] Fix login bug — **waiting** | Raw payload |
| RSS (12) | [rss] New release v2.0 — **done** | Agent processing log |
| Gmail (1) | [gmail] Meeting invite — **pending** | Approval buttons |

Top status bar: daemon status | active sessions | queue backlog

Settings page: Policy editor (YAML) | Source subscriptions | Prompt templates

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/status` | Daemon status |
| GET | `/api/envelopes` | List envelopes (filter by source, limit) |
| GET | `/api/envelopes/{id}` | Get envelope detail |
| POST | `/api/envelopes/{id}/approve` | Approve proposed action |
| POST | `/api/envelopes/{id}/dismiss` | Dismiss envelope |
| GET | `/api/sources` | List sources with unread counts |
| GET | `/api/settings/policies` | List policy files |
| PUT | `/api/settings/policies/{name}` | Save policy file |
| GET | `/api/settings/prompts` | List prompt templates |

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests
python -m pytest tests/ -v

# Run specific test suites
python -m pytest tests/test_github.py -v
python -m pytest tests/test_gmail.py -v
python -m pytest tests/test_store.py -v
python -m pytest tests/test_config.py -v

# Lint
ruff check loom/ tests/
```

## Implementation Status

| Module | Status | Notes |
|---|---|---|
| Core (Envelope, EventBus, Mailbox) | Complete | |
| Config system | Complete | YAML config load/save |
| State Store (SQLite) | Complete | SQLAlchemy + aiosqlite |
| GitHub adaptor | Complete | REST API polling, tested (37 tests) |
| Gmail adaptor | Complete | OAuth2 + Google API, tested (22 tests) |
| Policy Engine | Complete | YAML rule matching |
| Dispatcher | Complete | Policy evaluation + session spawning |
| Session Manager | Complete | claude-agent-sdk integration |
| Daemon bootstrap | In progress | CLI + wiring |
| Web UI API | In progress | FastAPI routes |
| RSS adaptor | Stub | |
| anet adaptor | Stub | |
| Frontend SPA | Not started | |

## License

MIT
