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
│  │            Mailbox (Core)           │  Receive → Store → Pub  │
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
│  └─────────────────────────────────────┘                         │
│             ▲  User approval / override                          │
└──────────────────────────────────────────────────────────────────┘
```

## Data Flow

1. **Ingest** — An adaptor polls an external source and normalizes events into an `Envelope`.
2. **Queue** — The Mailbox persists the envelope via SQLite and publishes to the event bus.
3. **Dispatch** — The Dispatcher evaluates policy rules and spawns a Claude Code session.
4. **Process** — The agent session executes the assigned prompt template and produces a result.
5. **Review** — The result surfaces in the Web UI or CLI. The user can approve or dismiss.
6. **Act** — On approval, Loom executes the action through the originating adaptor.

## Project Structure

```
loom/
├── config.py                # Config loading/saving (~/.loom/config.yaml)
├── daemon.py                # Daemon bootstrap, signal handling, adaptor factory
├── core/                    # Core mailbox engine
│   ├── envelope.py          #   Envelope data model + EnvelopeStatus enum
│   ├── eventbus.py          #   In-process async pub/sub
│   └── mailbox.py           #   Mailbox: receive → store → publish
├── adaptor/                 # External source adapters
│   ├── base.py              #   BaseAdaptor ABC
│   ├── github.py            #   GitHub REST API polling (issues + PRs)
│   ├── gmail.py             #   Gmail OAuth2 + Google API polling
│   ├── rss.py               #   RSS/Atom feed poller (stub)
│   └── anet.py              #   Agent Network peer (stub)
├── orchestrator/            # Agent coordination (claude-agent-sdk)
│   ├── session.py           #   Claude Code session manager
│   ├── dispatcher.py        #   Envelope → agent dispatch + session completion
│   └── policy.py            #   YAML policy engine
├── state/                   # Persistence layer
│   └── store.py             #   SQLite store (SQLAlchemy + aiosqlite)
├── cli/                     # CLI entry point
│   ├── main.py              #   argparse parser + command handlers
│   └── view/                #   Rich rendering (tables, themes, doctor)
├── webui/                   # Web interface
│   └── app.py               #   FastAPI REST API (wired to DaemonContext)
├── observability/           # Monitoring & metrics
│   └── metrics.py           #   Daemon status, session count
├── policies/                # Default policy files
│   └── github.yaml          #   GitHub routing rules
└── prompts/                 # Default prompt templates
    └── prompt_github_issue.md
```

## Quick Start

```bash
# Install (dev mode)
pip install -e ".[dev]"

# For Gmail support
pip install -e ".[gmail]"

# Configure a GitHub source
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
loom source add github --repo owner/repo --events issues,pull_requests

# Start the daemon (background)
loom daemon

# Check status
loom status

# View inbox
loom inbox

# Approve or dismiss
loom approve <envelope_id>
loom reject <envelope_id>

# Stop the daemon
kill $(cat ~/.loom/data/loom.pid)
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
    ├── loom.db          # SQLite state (envelopes + adaptor state)
    ├── loom.pid         # Daemon PID file
    └── loom.log         # Daemon log output
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

## CLI Reference

```
loom inbox [--source github] [--status pending] [--limit 20]
loom show <envelope_id>
loom approve <envelope_id>
loom reject <envelope_id> [--reason "..."]
loom daemon                                   # Start daemon (background)
loom daemon -f                                # Start daemon (foreground)
loom status                                   # Queue backlog + daemon status
loom doctor                                   # Diagnose local setup
loom source add github --repo owner/repo [--events issues,pull_requests]
loom source add gmail --credentials path/to/secrets.json
loom source list
loom ui                                       # Open web UI in browser
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/status` | Daemon status (online, active sessions, backlog) |
| GET | `/api/envelopes` | List envelopes (filter by source, limit) |
| GET | `/api/envelopes/{id}` | Get envelope detail |
| POST | `/api/envelopes/{id}/approve` | Approve proposed action |
| POST | `/api/envelopes/{id}/dismiss` | Dismiss envelope |
| GET | `/api/sources` | List sources with unread counts |
| GET | `/api/settings/policies` | List policy files |
| PUT | `/api/settings/policies/{name}` | Save policy file |
| GET | `/api/settings/prompts` | List prompt templates |

## Adaptors

### GitHub (REST API Polling)

Polls `GET /repos/{owner}/{repo}/issues?since={cursor}` for incremental updates. Designed for local dev machines — no public endpoint or webhook required.

Features: `since` cursor for incremental updates, ETag conditional requests (304 support), rate limit backoff, per-repo polling interval, event type and label filtering, cursor persistence across restarts.

Actions: `comment`, `close`, `label` (add/remove). See [docs/github-example.md](docs/github-example.md) for an end-to-end walkthrough.

### Gmail (Google API + OAuth2)

Polls Gmail via Google API with OAuth2 browser-based auth. Token cached locally and auto-refreshed.

Features: configurable query string, APScheduler polling, full MIME body decoding, thread-aware headers, seen-set persistence, proxy support.

Actions: `reply` (with threading headers), `archive`, `label`, `trash`.

## Development

```bash
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v

# Lint
ruff check loom/ tests/

# Run pre-commit
pre-commit run --all-files
```

## Implementation Status

| Module | Status | Tests |
|---|---|---|
| Core (Envelope, EventBus, Mailbox) | Complete | - |
| Config system | Complete | 11 |
| State Store (SQLite) | Complete | 28 |
| GitHub adaptor | Complete | 37 |
| Gmail adaptor | Complete | 22 |
| Policy Engine | Complete | - |
| Dispatcher + session completion | Complete | 3 |
| Session Manager (claude-agent-sdk) | Complete | - |
| Daemon bootstrap | Complete | 7 |
| CLI (argparse + Rich) | Complete | 9 |
| WebUI API routes | Complete | - |
| RSS adaptor | Stub | - |
| anet adaptor | Stub | - |
| Frontend SPA | Not started | - |

## License

MIT
