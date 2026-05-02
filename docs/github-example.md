# End-to-End Example: GitHub Issue Monitoring

This walkthrough shows how Loom monitors a GitHub repo, triages incoming issues with Claude, and surfaces results for your review.

## Prerequisites

```bash
# Install Loom with dev deps
pip install -e ".[dev]"

# Set your GitHub token (needs repo read + issues read/write)
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
```

See [github-token.md](github-token.md) for how to create a suitable token.

## Step 1: Configure the source

```bash
$ loom source add github --repo octocat/hello-world --events issues,pull_requests

  Added: octocat/hello-world (events=['issues', 'pull_requests'], interval=120s, state=all)

GitHub source(s) saved to config. Token: GITHUB_TOKEN env
Run `loom daemon` to start monitoring.
```

This writes to `~/.loom/config.yaml`:

```yaml
sources:
  - kind: github
    owner: octocat
    repo: hello-world
    poll_interval: 120
    events: ["issues", "pull_requests"]
    state: "all"
```

## Step 2: Verify setup

```bash
$ loom doctor

  ✓  ~/.loom directory        ~/.loom
  ✓  policies dir              ~/.loom/policies
  ✓  prompts dir               ~/.loom/prompts
  ✓  data dir                  ~/.loom/data
  ✓  config.yaml               1 source(s), daemon @ 127.0.0.1:8732
  ✓  github · octocat/hello-world   GITHUB_TOKEN set
```

## Step 3: Start the daemon

```bash
$ loom daemon

Loom daemon started (PID 12345)
  API: http://127.0.0.1:8732
  Log: ~/.loom/data/loom.log
  PID: ~/.loom/data/loom.pid
```

Behind the scenes, the daemon:

1. Initializes SQLite at `~/.loom/data/loom.db`
2. Creates EventBus + Mailbox
3. Loads policy rules from `~/.loom/policies/*.yaml`
4. Builds a `GitHubAdaptor` and restores any saved cursors
5. Starts polling `GET /repos/octocat/hello-world/issues?since={cursor}` every 120 seconds
6. Starts the FastAPI server on port 8732

## Step 4: What happens when a new issue appears

Someone opens a bug report:

> **Title:** "Login returns 500 on Safari 17"
> **Labels:** bug, P0

### The data flow:

```
GitHub API response
    │
    ▼
GitHubAdaptor._poll_source()
    │  GET /repos/octocat/hello-world/issues?since=2024-01-01T00:00:00Z
    │  Returns issue #42
    │
    ▼
GitHubAdaptor.normalize()
    │  Creates Envelope:
    │    source="github"
    │    source_id="octocat/hello-world#42"
    │    title="[issue] Login returns 500 on Safari 17"
    │    labels=["bug", "P0", "issue", "open"]
    │    priority=2  (bug label detected)
    │
    ▼
Mailbox.receive()
    │  Saves envelope to SQLite (status=PENDING)
    │  Publishes "new_envelope" to EventBus
    │
    ▼
Dispatcher._on_new_envelope()
    │  PolicyEngine evaluates rules:
    │    Rule 1 "Critical GitHub issues" matches (source=github, labels contains bug+P0)
    │    → priority=3, prompt="prompt_github_issue", tools=[Read,Grep,WebFetch]
    │  Updates envelope status → PROCESSING
    │
    ▼
SessionManager.spawn()
    │  Creates ClaudeSDKClient with policy settings
    │  Sends the prompt template filled with envelope data:
    │
    │    "You are a personal assistant that triages GitHub issues...
    │     Source: github
    │     Title: Login returns 500 on Safari 17
    │     Labels: bug, P0
    │     Author: someone
    │     Link: https://github.com/octocat/hello-world/issues/42
    │     Content: <issue body>"
    │
    │  Claude processes the issue and returns analysis
    │
    ▼
Dispatcher.handle_session_complete()
    │  Sets envelope.agent_summary = Claude's analysis
    │  Updates envelope status → WAITING_APPROVAL
    │  Saves to SQLite
```

## Step 5: Review the result

### Via CLI

```bash
$ loom inbox

  ID        Source    Title                              Status              Priority
  ──────────────────────────────────────────────────────────────────────────────────
  a1b2c3d4  github    [issue] Login returns 500 on...    waiting_approval    3

$ loom show a1b2c3d4

  Envelope: a1b2c3d4
  Source:   github · octocat/hello-world#42
  Title:    [issue] Login returns 500 on Safari 17
  Status:   waiting_approval
  Priority: 3 (urgent)
  Labels:   bug, P0, issue, open

  Agent Summary:
    This is a critical bug affecting Safari 17 users. The 500 error during
    login suggests a server-side compatibility issue with Safari's cookie
    handling. Recommended action: investigate the session middleware for
    SameSite cookie attributes. A draft reply is prepared.

  Proposed Action:
    type: comment
    body: "Thanks for reporting. We've identified this as a Safari 17 cookie
          compatibility issue and are working on a fix."
```

### Via API

```bash
$ curl -s http://localhost:8732/api/envelopes?limit=5 | python3 -m json.tool

[
  {
    "id": "a1b2c3d4",
    "source": "github",
    "source_id": "octocat/hello-world#42",
    "title": "[issue] Login returns 500 on Safari 17",
    "status": "waiting_approval",
    "priority": 3,
    "labels": ["bug", "P0", "issue", "open"],
    "agent_summary": "This is a critical bug...",
    "proposed_action": {
      "type": "comment",
      "body": "Thanks for reporting..."
    }
  }
]
```

## Step 6: Approve or reject

### Approve — posts the comment to GitHub

```bash
$ loom approve a1b2c3d4

  Approved: a1b2c3d4
```

Or via API:

```bash
$ curl -X POST http://localhost:8732/api/envelopes/a1b2c3d4/approve

{"status": "approved", "id": "a1b2c3d4"}
```

This transitions the envelope to `DONE` and (when action execution is wired) posts the comment via `POST /repos/octocat/hello-world/issues/42/comments`.

### Reject — marks as dismissed

```bash
$ loom reject a1b2c3d4 --reason "duplicate of #38"

  Rejected: a1b2c3d4 (duplicate of #38)
```

## Step 7: Stop the daemon

```bash
$ kill $(cat ~/.loom/data/loom.pid)
```

The daemon saves GitHub cursors to SQLite before exiting, so it picks up where it left off on next start.

## What's running under the hood

```
$ loom status

  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Online   Sessions   Backlog
  ✓ Yes    0          1
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  done                0
  dismissed           0
  failed              0
  pending             0
  processing          0
  waiting_approval    1
  daemon pid=12345
```

## Policy customization

Edit `~/.loom/policies/github.yaml` to change routing rules:

```yaml
rules:
  - name: "Critical bugs"
    match:
      source: github
      labels: ["bug", "P0"]
    action:
      priority: 3
      prompt: "prompt_github_issue"
      tools: ["Read", "Grep", "WebFetch", "Bash"]
      auto_approve: false

  - name: "Everything else"
    match:
      source: github
    action:
      priority: 1
      prompt: "prompt_github_issue"
      auto_approve: false
```

Edit `~/.loom/prompts/prompt_github_issue.md` to customize the triage prompt. Variables available: `{source}`, `{title}`, `{body}`, `{source_id}`, `{labels}`, `{metadata[key]}`.
