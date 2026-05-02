"""GitHub adaptor — REST API polling for issues and PRs.

Strategy:
  - Poll ``GET /repos/{owner}/{repo}/issues`` with ``since`` parameter for
    incremental updates (issues + PRs — PRs are a superset in GitHub's API).
  - Store per-repo cursor (last ``updated_at`` seen) in the state store.
  - Deduplicate by ``source_id`` — skip items already in the mailbox.
  - Respect rate limits via ``X-RateLimit-*`` response headers.
  - Support conditional requests (``ETag`` / ``If-None-Match``) to save quota.

Why polling instead of webhooks:
  - Runs on a local dev machine without a public endpoint.
  - ``since`` cursor makes polling effectively incremental.
  - 5000 req/hr (authenticated) is more than enough for typical usage.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from loom.adaptor.base import BaseAdaptor
from loom.core.envelope import Envelope, EnvelopeStatus

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
DEFAULT_POLL_INTERVAL = 120  # seconds


@dataclass
class GitHubSourceConfig:
    """Configuration for one GitHub repo subscription."""

    owner: str
    repo: str
    poll_interval: int = DEFAULT_POLL_INTERVAL
    state: str = "all"  # "open", "closed", "all"
    labels_filter: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=lambda: ["issues", "pull_requests"])
    group: str = ""


class GitHubAdaptor(BaseAdaptor):
    """Polls GitHub repos for updated issues and pull requests."""

    name = "github"

    def __init__(self, token: str | None = None, proxy: str | None = None) -> None:
        if token is None:
            token = os.environ.get("GITHUB_TOKEN", "")
        self._token = token
        self._proxy = proxy
        self._sources: dict[str, GitHubSourceConfig] = {}  # key = "owner/repo"
        self._cursors: dict[str, str] = {}  # key → ISO timestamp
        self._etags: dict[str, str] = {}
        self._seen_ids: set[str] = set()  # dedup source_ids
        self._running = False
        self._client: httpx.AsyncClient | None = None
        self._poll_task: Any | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def add_source(self, config: GitHubSourceConfig) -> None:
        """Add a repo to monitor."""
        key = f"{config.owner}/{config.repo}"
        self._sources[key] = config
        # Initialize cursor to now if not set (only picks up *new* updates)
        if key not in self._cursors:
            self._cursors[key] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.info("GitHub source added: %s (poll every %ds)", key, config.poll_interval)

    def remove_source(self, owner: str, repo: str) -> None:
        key = f"{owner}/{repo}"
        self._sources.pop(key, None)
        self._cursors.pop(key, None)
        self._etags.pop(key, None)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self._sources:
            logger.warning("No GitHub sources configured — adaptor idle")
            return

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        self._client = httpx.AsyncClient(
            base_url=GITHUB_API,
            headers=headers,
            timeout=30.0,
            proxy=self._proxy,
        )
        self._running = True

        # Start background polling loop
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("GitHub adaptor started — monitoring %d repo(s)", len(self._sources))

    async def stop(self) -> None:
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("GitHub adaptor stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Polling loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Main polling loop — iterates over all sources with per-source intervals."""
        while self._running:
            for key, config in list(self._sources.items()):
                if not self._running:
                    break
                try:
                    await self._poll_source(key, config)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 403:
                        # Rate limited — check reset time and back off
                        reset = int(exc.response.headers.get("X-RateLimit-Reset", "0"))
                        if reset:
                            wait = max(reset - int(datetime.now(UTC).timestamp()), 10)
                            logger.warning("GitHub rate limited — backing off %ds", wait)
                            await asyncio.sleep(wait)
                    else:
                        logger.error("GitHub API error for %s: %s", key, exc)
                except Exception as exc:
                    logger.error("Error polling %s: %s", key, exc)

            # Sleep for the shortest configured interval
            min_interval = min(
                (c.poll_interval for c in self._sources.values()), default=DEFAULT_POLL_INTERVAL
            )
            await asyncio.sleep(min_interval)

    async def _poll_source(self, key: str, config: GitHubSourceConfig) -> None:
        """Poll a single repo for updated issues/PRs."""
        assert self._client is not None

        since = self._cursors.get(key)
        if not since:
            return

        url = f"/repos/{key}/issues"
        params: dict[str, Any] = {
            "since": since,
            "state": config.state,
            "sort": "updated",
            "direction": "asc",
            "per_page": 100,
        }

        # Conditional request with ETag
        headers: dict[str, str] = {}
        etag = self._etags.get(key)
        if etag:
            headers["If-None-Match"] = etag

        resp = await self._client.get(url, params=params, headers=headers)

        # 304 Not Modified — nothing new
        if resp.status_code == 304:
            return

        resp.raise_for_status()

        # Save ETag for next conditional request
        new_etag = resp.headers.get("ETag")
        if new_etag:
            self._etags[key] = new_etag

        items = resp.json()
        if not items:
            return

        latest_updated = since

        for item in items:
            envelope = await self.normalize(item)
            envelope.group = config.group

            # Dedup: skip if we've already processed this source_id
            if envelope.source_id in self._seen_ids:
                continue
            self._seen_ids.add(envelope.source_id)

            # Filter by event type
            is_pr = "pull_request" in item
            if is_pr and "pull_requests" not in config.events:
                continue
            if not is_pr and "issues" not in config.events:
                continue

            # Filter by labels if configured
            if config.labels_filter:
                item_labels = {lbl["name"] for lbl in item.get("labels", [])}
                if not any(lbl in item_labels for lbl in config.labels_filter):
                    continue

            await self._emit(envelope)
            logger.info(
                "New GitHub envelope: %s [%s] %s",
                envelope.source_id,
                envelope.labels,
                envelope.title[:60],
            )

            # Track the latest updated_at for cursor advancement
            item_updated = item.get("updated_at", "")
            if item_updated > latest_updated:
                latest_updated = item_updated

        # Advance cursor
        self._cursors[key] = latest_updated

    # ------------------------------------------------------------------
    # Normalize
    # ------------------------------------------------------------------

    async def normalize(self, raw_event: Any) -> Envelope:
        """Convert a GitHub issue/PR API response into an Envelope."""
        item = raw_event  # dict from GitHub API
        is_pr = "pull_request" in item
        kind = "PR" if is_pr else "issue"
        repo_url = item.get("repository_url", "")
        # Extract owner/repo from repository_url
        # e.g. "https://api.github.com/repos/owner/repo"
        repo_full = repo_url.replace("https://api.github.com/repos/", "") if repo_url else ""

        number = item.get("number", 0)
        source_id = f"{repo_full}#{number}"

        # Build labels list
        labels = [lbl["name"] for lbl in item.get("labels", [])]
        label_colors: dict[str, str] = {
            lbl["name"]: lbl["color"]
            for lbl in item.get("labels", [])
            if lbl.get("name") and lbl.get("color")
        }
        if is_pr:
            labels.append("pr")
        else:
            labels.append("issue")
        state = item.get("state", "")
        if state:
            labels.append(state)

        # Build body — include the key info
        body_parts = []
        if item.get("body"):
            body_parts.append(item["body"])
        if is_pr:
            pr_data = item.get("pull_request", {})
            body_parts.append(f"PR state: {pr_data.get('state', state)}")
            if pr_data.get("merged"):
                body_parts.append("Status: merged")
            body_parts.append(f"Draft: {pr_data.get('draft', False)}")

        user = item.get("user", {}).get("login", "unknown")
        html_url = item.get("html_url", "")

        return Envelope(
            source=self.name,
            source_id=source_id,
            title=f"[{kind}] {item.get('title', 'Untitled')}",
            body="\n\n".join(body_parts) if body_parts else "",
            status=EnvelopeStatus.PENDING,
            priority=2 if any(tag in labels for tag in ("bug", "P0", "urgent")) else 1,
            labels=labels,
            metadata={
                "repo": repo_full,
                "number": number,
                "kind": kind,
                "state": state,
                "user": user,
                "html_url": html_url,
                "created_at": item.get("created_at", ""),
                "updated_at": item.get("updated_at", ""),
                "comments": item.get("comments", 0),
                "reactions": item.get("reactions", {}).get("total_count", 0)
                if item.get("reactions")
                else 0,
                "assignees": [a.get("login", "") for a in item.get("assignees", [])],
                "milestone": (item.get("milestone") or {}).get("title", ""),
                "label_colors": label_colors,
            },
        )

    # ------------------------------------------------------------------
    # Execute actions
    # ------------------------------------------------------------------

    async def execute_action(self, envelope: Envelope, action: dict) -> None:
        """Execute an approved action on GitHub.

        Supported actions:
        - ``{"type": "comment", "body": "..."}``  — post a comment
        - ``{"type": "close"}``                    — close an issue/PR
        - ``{"type": "label", "add": [...], "remove": [...]}`` — modify labels
        """
        assert self._client is not None
        repo = envelope.metadata.get("repo", "")
        number = envelope.metadata.get("number", 0)
        action_type = action.get("type", "")

        if action_type == "comment":
            resp = await self._client.post(
                f"/repos/{repo}/issues/{number}/comments",
                json={"body": action.get("body", "")},
            )
            resp.raise_for_status()
            logger.info("Comment posted on %s#%d", repo, number)

        elif action_type == "close":
            resp = await self._client.patch(
                f"/repos/{repo}/issues/{number}",
                json={"state": "closed"},
            )
            resp.raise_for_status()
            logger.info("Closed %s#%d", repo, number)

        elif action_type == "label":
            if action.get("add"):
                resp = await self._client.post(
                    f"/repos/{repo}/issues/{number}/labels",
                    json={"labels": action["add"]},
                )
                resp.raise_for_status()
            if action.get("remove"):
                for label in action["remove"]:
                    resp = await self._client.delete(
                        f"/repos/{repo}/issues/{number}/labels/{label}",
                    )
                    resp.raise_for_status()
            logger.info("Labels updated on %s#%d", repo, number)

        else:
            logger.warning("Unknown GitHub action type: %s", action_type)

    # ------------------------------------------------------------------
    # Persistence helpers (called by state store)
    # ------------------------------------------------------------------

    def get_cursors(self) -> dict[str, str]:
        """Export current cursors for persistence."""
        return dict(self._cursors)

    def restore_cursors(self, cursors: dict[str, str]) -> None:
        """Restore cursors from previous run."""
        self._cursors.update(cursors)

    def export_seen(self) -> list[str]:
        return list(self._seen_ids)

    def restore_seen(self, entries: list[str]) -> None:
        self._seen_ids.update(e for e in entries if isinstance(e, str))
