# End-to-End Example: RSS Feed Monitoring

This walkthrough shows how Loom monitors RSS/Atom feeds, summarizes new items with Claude, and surfaces results for your review.

## Prerequisites

```bash
# Install Loom
pip install -e .
```

No API tokens or credentials are needed for RSS — feeds are publicly accessible.

## Step 1: Configure the source

```bash
$ loom source add rss --url https://hnrss.org/newest?points=100 --interval 300

  RSS source saved: https://hnrss.org/newest?points=100 (interval=300s)
  Run `loom daemon` to start monitoring.
```

This writes to `~/.loom/config.yaml`:

```yaml
sources:
  - kind: rss
    url: https://hnrss.org/newest?points=100
    poll_interval: 300
```

You can add multiple feeds — one `RSSAdaptor` handles them all:

```bash
$ loom source add rss --url https://blog.rust-lang.org/feed.xml
$ loom source add rss --url https://go.dev/blog/feed.atom
```

## Step 2: Verify setup

```bash
$ loom doctor

  ✓  ~/.loom directory        ~/.loom
  ✓  policies dir              ~/.loom/policies
  ✓  prompts dir               ~/.loom/prompts
  ✓  data dir                  ~/.loom/data
  ✓  config.yaml               3 source(s), daemon @ 127.0.0.1:8732
  ✓  rss · https://hnrss.org/newest?points=100   https://hnrss.org/newest?points=100
```

## Step 3: Start the daemon

```bash
$ loom daemon

Loom daemon started (PID 12345)
  Log: ~/.loom/data/loom.log
  PID: ~/.loom/data/loom.pid
```

Behind the scenes, the daemon:

1. Initializes SQLite at `~/.loom/data/loom.db`
2. Creates EventBus + Mailbox
3. Loads policy rules from `~/.loom/policies/*.yaml`
4. Builds an `RSSAdaptor` with the configured feeds
5. Starts polling each feed using HTTP GET with `If-None-Match` / `If-Modified-Since`
6. Starts the FastAPI server on port 8732

## Step 4: What happens when a new item appears

A new post appears on Hacker News:

> **Title:** "Show Loom: AI-assisted RSS triage"
> **Author:** jsmith
> **Tags:** show_hn, ai

### The data flow:

```
RSS feed HTTP response
    │
    ▼
RSSAdaptor._poll_feed()
    │  GET https://hnrss.org/newest?points=100
    │  200 OK — feedparser parses RSS XML
    │  Skips already-seen entries (dedup by GUID)
    │
    ▼
RSSAdaptor.normalize()
    │  Creates Envelope:
    │    source="rss"
    │    source_id="https://news.ycombinator.com/item?id=40404040"
    │    title="Show Loom: AI-assisted RSS triage"
    │    labels=["show_hn", "ai"]
    │    metadata.feed_title="Hacker News"
    │    metadata.link="https://news.ycombinator.com/item?id=40404040"
    │    metadata.author="jsmith"
    │
    ▼
Mailbox.receive()
    │  Saves envelope to SQLite (status=PENDING)
    │  Publishes "new_envelope" to EventBus
    │
    ▼
Dispatcher._on_new_envelope()
    │  PolicyEngine evaluates rules:
    │    Rule "RSS feed items" matches (source=rss)
    │    → priority=1, prompt="prompt_rss"
    │  Updates envelope status → PROCESSING
    │
    ▼
SessionManager.spawn()
    │  Sends the prompt template filled with envelope data:
    │
    │    "You are a personal assistant that triages RSS feed items...
    │     Feed: Hacker News
    │     Source URL: https://hnrss.org/newest?points=100
    │     Author: jsmith
    │     Tags: show_hn, ai
    │     Link: https://news.ycombinator.com/item?id=40404040
    │     Content: <item summary>"
    │
    │  Claude processes and returns analysis
    │
    ▼
Dispatcher.handle_session_complete()
    │  Sets envelope.agent_summary = Claude's analysis
    │  Updates envelope status → WAITING_APPROVAL
```

## Step 5: Review the result

### Via CLI

```bash
$ loom inbox

  ID        Source    Title                                Status              Priority
  ──────────────────────────────────────────────────────────────────────────────────
  a1b2c3d4  rss       Show Loom: AI-assisted RSS triage    waiting_approval    1

$ loom show a1b2c3d4

  Envelope: a1b2c3d4
  Source:   rss · https://news.ycombinator.com/item?id=40404040
  Title:    Show Loom: AI-assisted RSS triage
  Status:   waiting_approval
  Priority: 1 (normal)
  Labels:   show_hn, ai

  Agent Summary:
    This is a Show HN post for a tool called Loom that uses AI to triage
    RSS feed items. It's relevant if you're interested in AI-assisted
    information filtering tools. Key takeaway: uses Claude to summarize
    and prioritize feed entries before surfacing them.
```

### Via API

```bash
$ curl -s http://localhost:8732/api/envelopes?limit=5 | python3 -m json.tool

[
  {
    "id": "a1b2c3d4",
    "source": "rss",
    "source_id": "https://news.ycombinator.com/item?id=40404040",
    "title": "Show Loom: AI-assisted RSS triage",
    "status": "waiting_approval",
    "priority": 1,
    "labels": ["show_hn", "ai"],
    "agent_summary": "This is a Show HN post...",
    "metadata": {
      "feed_url": "https://hnrss.org/newest?points=100",
      "feed_title": "Hacker News",
      "link": "https://news.ycombinator.com/item?id=40404040",
      "author": "jsmith",
      "tags": ["show_hn", "ai"]
    }
  }
]
```

## Step 6: Approve or dismiss

RSS is read-only — approving means you've acknowledged the item. No action is sent back to the feed.

```bash
$ loom approve a1b2c3d4

  Approved: a1b2c3d4
```

Or dismiss:

```bash
$ loom reject a1b2c3d4 --reason "not relevant"

  Rejected: a1b2c3d4 (not relevant)
```

## Step 7: Stop the daemon

```bash
$ kill $(cat ~/.loom/data/loom.pid)
```

The daemon saves state before exiting, so it picks up where it left off on next start.

## Policy customization

Edit `~/.loom/policies/rss.yaml` to change routing rules:

```yaml
rules:
  - name: "AI-related feed items"
    match:
      source: rss
      labels: ["ai", "machine-learning"]
    action:
      priority: 2
      prompt: "prompt_rss"
      tools: ["Read", "WebFetch"]
      auto_approve: false

  - name: "All RSS items"
    match:
      source: rss
    action:
      priority: 1
      prompt: "prompt_rss"
      auto_approve: false
```

Edit `~/.loom/prompts/prompt_rss.md` to customize the triage prompt. Variables available: `{source}`, `{title}`, `{body}`, `{source_id}`, `{labels}`, `{metadata[key]}`.

## Supported feed formats

The RSS adaptor uses `feedparser` under the hood, which handles:

- **RSS 2.0** (e.g. Hacker News, most blogs)
- **RSS 1.0 / RDF** (e.g. some older feeds)
- **Atom** (e.g. GitHub releases, Go blog)
- **JSON Feed** (partial support)

## Configuration reference

| Field | Type | Default | Description |
|---|---|---|---|
| `url` | string | required | Feed URL (RSS, Atom, or RDF) |
| `poll_interval` | int | 300 | Polling interval in seconds |
| `title_filter` | list | `[]` | Keywords to filter items by title (OR match) |
