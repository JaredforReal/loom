# Loom

Loom is a mailbox and agent orchestration layer for Claude Code. It receives messages from external sources (GitHub, RSS, Gmail), dispatches them to Claude Code sessions for preprocessing (summarization, triage, classification), and surfaces results for user approval.

**Philosophy: help you read, not help you do.** The agent is a preprocessor, not a task executor.

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
│   ├── dispatcher.py        #   Envelope → agent dispatch + agent/mailbox toggle
│   └── policy.py            #   YAML policy engine (bundled + user rules)
├── state/                   # Persistence layer
│   └── store.py             #   SQLite store (SQLAlchemy + aiosqlite)
├── cli/                     # CLI entry point
│   ├── main.py              #   argparse parser + command handlers
│   └── view/                #   Rich rendering (tables, themes, doctor)
├── webui/                   # Web interface
│   └── app.py               #   FastAPI REST API (wired to DaemonContext)
├── observability/           # Monitoring & metrics
│   └── metrics.py           #   Daemon status, session count
├── policies/                # Bundled policy defaults
│   ├── github.yaml          #   GitHub routing rules
│   └── gmail.yaml           #   Gmail routing rules
└── prompts/                 # Bundled prompt templates
    ├── prompt_github_issue.md
    └── prompt_gmail.md
```

## Quick Start

```bash
# Install
pip install -e .

# For Gmail support
pip install -e ".[gmail]"

# Configure a GitHub source
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
loom source add github --repo owner/repo --events issues,pull_requests

# Start the daemon (background, default)
loom daemon

# Or start in foreground
loom daemon -f

# Check status
loom status

# View inbox
loom inbox

# Approve or dismiss
loom approve <envelope_id>
loom reject <envelope_id>

# Stop the daemon
loom down
```

## Mailbox / Agent Control

Mailbox (adaptors) and agent (Claude Code processor) can be toggled independently:

```bash
# Both running (default after `loom daemon`)
# - Adaptors collect envelopes
# - Agent processes them through Claude Code

# Pause agent, keep collecting
loom agent off     # Envelopes stay PENDING, no token consumption
loom agent on      # Resume processing, drain backlog

# Pause mailbox, keep processing
loom mailbox off   # Stop adaptors, agent processes pending backlog
loom mailbox on    # Restart adaptors

# Check status
loom agent status
loom mailbox status
```

Agent concurrency is controlled by `max_concurrent` in config (default: 3). The session manager uses a semaphore to enforce this — only N Claude Code sessions run simultaneously regardless of backlog size.

## Configuration

Loom stores all state in `~/.loom/`:

```
~/.loom/
├── config.yaml          # Daemon settings + source subscriptions
├── .env                 # Environment variables (GITHUB_TOKEN, etc.)
├── policies/            # User policy overrides (shadow bundled defaults)
├── prompts/             # User prompt overrides + per-source prompts
│   └── github/          #   Per-source prompts (e.g. github/acme-app.md)
├── credentials/         # OAuth tokens, API keys
└── data/
    ├── loom.db          # SQLite state (envelopes + adaptor state)
    ├── loom.pid         # Daemon PID file
    └── loom.log         # Daemon log output (rotating, 10MB)
```

### config.yaml

```yaml
daemon:
  host: "127.0.0.1"
  port: 8732
  proxy: "http://127.0.0.1:7890"   # Optional: HTTP/SOCKS proxy

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

### Policy Rules

Policies route envelopes to agent sessions. Bundled defaults are shipped with Loom; user rules in `~/.loom/policies/` take priority.

```yaml
# ~/.loom/policies/my-project.yaml
rules:
  - name: "vllm project issues"
    match:
      source: github
      source_id_pattern: "vllm-project/vllm#"
    action:
      priority: 2
      prompt: "prompt_github_issue"     # Bundled or custom template name
      model: sonnet                      # Override model
      max_turns: 5                       # Limit agent turns
      skills: ["vllm-expert"]            # SDK skills to inject
      cwd: "/path/to/local/vllm/clone"   # Agent working directory
      auto_approve: false
```

Match fields: `source`, `labels`, `source_id_pattern` (regex), `title_pattern` (regex).

### Prompt Templates

Three-layer resolution (last wins):

1. **Bundled**: `loom/prompts/*.md` (shipped with the package)
2. **User**: `~/.loom/prompts/*.md` (overrides bundled)
3. **Per-source**: `~/.loom/prompts/<source>/<name>.md` (e.g. `github/acme-app.md`)

Templates use Python format syntax with envelope fields: `{source}`, `{title}`, `{body}`, `{labels}`, `{source_id}`, `{metadata[user]}`, `{metadata[html_url]}`, etc. Missing metadata keys produce empty strings instead of errors.

## CLI Reference

```
# Daemon management
loom daemon                                   # Start daemon (background)
loom daemon -f                                # Start daemon (foreground)
loom up                                       # Alias for `loom daemon`
loom down                                     # Stop daemon

# Mailbox / Agent control
loom agent on                                 # Enable agent processing + drain pending
loom agent off                                # Pause agent (mailbox keeps collecting)
loom agent status                             # Show agent state
loom mailbox on                               # Start adaptors (collect envelopes)
loom mailbox off                              # Stop adaptors (agent keeps processing)
loom mailbox status                           # Show adaptor state

# Envelope operations
loom inbox [--source github] [--status pending] [--limit 20]
loom show <envelope_id>
loom approve <envelope_id>
loom reject <envelope_id> [--reason "..."]

# Source management
loom source add github --repo owner/repo [--events issues,pull_requests]
loom source add gmail --credentials path/to/secrets.json
loom source list

# System
loom status                                   # Queue backlog + daemon status
loom doctor                                   # Diagnose local setup
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

Features: `since` cursor for incremental updates, ETag conditional requests (304 support), rate limit backoff, per-repo polling interval, event type and label filtering, cursor persistence across restarts, proxy support.

Actions: `comment`, `close`, `label` (add/remove). See [docs/github-example.md](docs/github-example.md) for an end-to-end walkthrough.

### Gmail (Google API + OAuth2)

Polls Gmail via Google API with OAuth2 browser-based auth. Token cached locally and auto-refreshed.

Features: configurable query string, APScheduler polling, full MIME body decoding, thread-aware headers, seen-set persistence, proxy support (HTTP/SOCKS).

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
| Config system + PID/proxy | Complete | 17 |
| State Store (SQLite) | Complete | 28 |
| GitHub adaptor | Complete | 37 |
| Gmail adaptor | Complete | 22 |
| Policy Engine (bundled + user) | Complete | 8 |
| Dispatcher + agent/mailbox toggle | Complete | 8 |
| Session Manager (semaphore concurrency) | Complete | 6 |
| Prompt loading (3-layer) | Complete | 6 |
| Daemon bootstrap | Complete | 7 |
| CLI (argparse + Rich) | Complete | 9 |
| WebUI API routes | Complete | - |
| RSS adaptor | Stub | - |
| anet adaptor | Stub | - |
| Frontend SPA | Not started | - |

## License

MIT
