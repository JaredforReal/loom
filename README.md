# Loom

**Make AI work before you ask. Stop drowning in feeds, stay on top effortlessly.**

> 让 AI 不再等你开口。告别信息洪流，轻松掌控全局。

Loom is a proactive AI agent that monitors your GitHub issues, emails, RSS feeds, and arXiv papers — triages them with Claude, and surfaces only what matters. You review, you approve. The AI does the preprocessing so you don't have to.

**Key features:**

- **Multi-source ingestion** — GitHub, Gmail, RSS, arXiv via pluggable adaptors
- **AI-powered triage** — Claude reads, summarizes, classifies urgency, and proposes actions
- **Kanban Web UI** — Visual inbox with source grouping, label colors, and markdown rendering
- **Policy engine** — YAML-driven routing rules to customize agent behavior per source
- **Agent orchestration** — Claude Code SDK sessions with concurrency control and auto-approve

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  External Sources                                                │
│  ┌────────┐ ┌─────┐ ┌───────┐ ┌──────┐                          │
│  │ GitHub │ │ RSS │ │ Gmail │ │ arXiv│  ...                      │
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

```
Ingest → Queue → Dispatch → Process → Review → Action
  │         │        │          │         │        │
  ▼         ▼        ▼          ▼         ▼        ▼
Poll     SQLite   Policy     Claude    Kanban   Execute
sources  + EventBus match    session   UI/CLI   action
```

1. **Ingest** — An adaptor polls an external source and normalizes events into an `Envelope`.
2. **Queue** — The Mailbox persists the envelope via SQLite and publishes to the event bus.
3. **Dispatch** — The Dispatcher evaluates policy rules and spawns a Claude Code session.
4. **Process** — The agent session executes the assigned prompt template and produces a result.
5. **Review** — The result surfaces in the Web UI or CLI. The user can approve or dismiss.
6. **Action** — On approval, Loom executes the action through the originating adaptor.

## Quick Start

```bash
# Install
pip install -e .

# Configure a GitHub source
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
loom source add github --repo owner/repo --events issues,pull_requests

# Start the daemon
loom up          # builds frontend, starts daemon, opens browser

# CLI workflow
loom inbox
loom status

# Control agent vs mailbox independently
loom agent off    # pause AI processing, keep collecting
loom mailbox off  # stop collection, keep processing backlog
```

## Project Structure

```
loom/
├── config.py                # Config loading/saving (~/.loom/config.yaml)
├── daemon.py                # Daemon bootstrap, signal handling, adaptor factory
├── api_server.py            # FastAPI REST API
├── core/                    # Core mailbox engine
│   ├── envelope.py          #   Envelope data model + EnvelopeStatus enum
│   ├── eventbus.py          #   In-process async pub/sub
│   └── mailbox.py           #   Mailbox: receive → store → publish
├── adaptor/                 # External source adapters
│   ├── base.py              #   BaseAdaptor ABC
│   ├── github.py            #   GitHub REST API polling (issues + PRs)
│   ├── gmail.py             #   Gmail OAuth2 + Google API polling
│   ├── rss.py               #   RSS/Atom feed poller
│   ├── arxiv.py             #   arXiv Search API (categories + keywords)
│   └── anet.py              #   Agent Network peer (stub)
├── orchestrator/            # Agent coordination (claude-agent-sdk)
│   ├── session.py           #   Claude Code session manager
│   ├── dispatcher.py        #   Envelope → agent dispatch + agent/mailbox toggle
│   └── policy.py            #   YAML policy engine (bundled + user rules)
├── state/                   # Persistence layer
│   └── store.py             #   SQLite store (SQLAlchemy + aiosqlite)
├── cli/                     # CLI entry point
│   └── main.py              #   argparse parser + Rich rendering
├── webui/                   # Web interface
│   ├── app.py               #   FastAPI SPA mount
│   └── frontend/            #   React + TypeScript + Tailwind + shadcn/ui
├── policies/                # Bundled policy defaults
└── prompts/                 # Bundled prompt templates
```

## Configuration

Loom stores all state in `~/.loom/`:

```
~/.loom/
├── config.yaml          # Daemon settings + source subscriptions
├── .env                 # Environment variables (GITHUB_TOKEN, etc.)
├── policies/            # User policy overrides (shadow bundled defaults)
├── prompts/             # User prompt overrides + per-source prompts
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

  - kind: arxiv
    categories: ["cs.AI", "cs.CL"]
    keywords: ["LLM", "reasoning"]
    poll_interval: 43200
    max_results: 50

  - kind: rss
    url: "https://blog.example.com/feed.xml"
    poll_interval: 300

  - kind: gmail
    client_secrets: "~/.loom/credentials/gmail-client-secrets.json"
    query: "is:unread -in:chats newer_than:1d"
    poll_seconds: 30
```

### Policy Rules

Policies route envelopes to agent sessions. User rules in `~/.loom/policies/` override bundled defaults.

```yaml
rules:
  - name: "vllm project issues"
    match:
      source: github
      source_id_pattern: "vllm-project/vllm#"
    action:
      priority: 2
      prompt: "prompt_github_issue"
      model: sonnet
      max_turns: 5
      cwd: "/path/to/local/vllm/clone"
      auto_approve: false
```

Match fields: `source`, `labels`, `source_id_pattern` (regex), `title_pattern` (regex).

### Prompt Templates

Three-layer resolution (last wins):

1. **Bundled**: `loom/prompts/*.md`
2. **User**: `~/.loom/prompts/*.md` (overrides bundled)
3. **Per-source**: `~/.loom/prompts/<source>/<name>.md`

Templates use Python format syntax: `{source}`, `{title}`, `{body}`, `{labels}`, `{source_id}`, `{metadata[user]}`, etc.

## CLI Reference

| Command | Description |
|---------|-------------|
| `loom up` | Build frontend, start daemon, open browser |
| `loom daemon [-f]` | Start daemon (background / foreground) |
| `loom down` | Stop daemon |
| `loom inbox` | List envelopes (Rich table) |
| `loom show <id>` | Envelope detail view |
| `loom approve <id>` | Approve proposed action |
| `loom reject <id>` | Dismiss envelope |
| `loom agent on/off` | Toggle AI processing |
| `loom mailbox on/off` | Toggle source collection |
| `loom source add github --repo owner/repo` | Add GitHub source |
| `loom source add arxiv --categories cs.AI,cs.CL` | Add arXiv source |
| `loom source add rss --url <url>` | Add RSS feed |
| `loom status` | Queue backlog + daemon status |
| `loom doctor` | Diagnose local setup |
| `loom ui` | Open web UI in browser |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Daemon status |
| GET | `/api/envelopes` | List envelopes (filter by source, group, prefix) |
| GET | `/api/envelopes/{id}` | Get envelope detail |
| POST | `/api/envelopes/{id}/approve` | Approve proposed action |
| POST | `/api/envelopes/{id}/dismiss` | Dismiss envelope |
| GET | `/api/sources` | List sources with unread counts |
| GET | `/api/groups` | List groups with unread counts |
| GET/PUT | `/api/settings/policies/{name}` | Read/write policy files |
| GET | `/api/settings/prompts` | List prompt templates |

## Adaptors

### GitHub (REST API Polling)

Polls `GET /repos/{owner}/{repo}/issues?since={cursor}` for incremental updates. No webhooks required — designed for local dev machines.

Features: `since` cursor, ETag conditional requests, rate limit backoff, per-repo polling, event type and label filtering, proxy support.

Actions: `comment`, `close`, `label`.

### arXiv (Search API)

Queries the arXiv Search API by categories and keywords with `submittedDate` range filtering for incremental fetches.

Features: category + keyword filtering, incremental date-based polling, configurable max results.

### RSS / Atom

HTTP polling with `feedparser` for RSS 2.0/Atom/RDF feeds. ETag/Last-Modified conditional requests.

### Gmail (Google API + OAuth2)

Polls Gmail via Google API with OAuth2 browser-based auth. Token cached locally and auto-refreshed.

Features: configurable query string, thread-aware headers, proxy support.

Actions: `reply` (with threading), `archive`, `label`, `trash`.

## Development

```bash
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v

# Lint
ruff check loom/ tests/

# Frontend dev
cd loom/webui/frontend
npm install
npm run dev     # Vite on :5173, proxies /api → :8732
```

## License

MIT
