"""Tests for loom.adaptor.github — GitHub REST API polling adaptor."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx

from loom.adaptor.github import (
    GITHUB_API,
    GitHubAdaptor,
    GitHubSourceConfig,
)
from loom.core.envelope import Envelope, EnvelopeStatus

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def _make_issue(
    number: int = 1,
    title: str = "Test issue",
    body: str | None = "Something is broken",
    state: str = "open",
    labels: list[dict] | None = None,
    updated_at: str = "2025-06-01T12:00:00Z",
    user: str = "alice",
    repo: str = "acme/app",
) -> dict[str, Any]:
    """Build a minimal GitHub issue API response dict."""
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "labels": labels or [],
        "updated_at": updated_at,
        "created_at": "2025-06-01T10:00:00Z",
        "user": {"login": user},
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "repository_url": f"https://api.github.com/repos/{repo}",
        "comments": 2,
        "assignees": [],
        "milestone": None,
        "reactions": {"total_count": 3},
    }


def _make_pr(
    number: int = 10,
    title: str = "Fix login bug",
    body: str = "This PR fixes the login flow",
    state: str = "open",
    labels: list[dict] | None = None,
    updated_at: str = "2025-06-01T13:00:00Z",
    user: str = "bob",
    repo: str = "acme/app",
    merged: bool = False,
    draft: bool = False,
) -> dict[str, Any]:
    """Build a minimal GitHub PR API response dict."""
    issue = _make_issue(
        number=number,
        title=title,
        body=body,
        state=state,
        labels=labels,
        updated_at=updated_at,
        user=user,
        repo=repo,
    )
    issue["pull_request"] = {
        "url": f"https://api.github.com/repos/{repo}/pulls/{number}",
        "html_url": f"https://github.com/{repo}/pull/{number}",
        "state": state,
        "merged": merged,
        "draft": draft,
    }
    issue["html_url"] = f"https://github.com/{repo}/pull/{number}"
    return issue


def _source_config(
    owner: str = "acme",
    repo: str = "app",
    events: list[str] | None = None,
    labels_filter: list[str] | None = None,
    poll_interval: int = 60,
    state: str = "all",
) -> GitHubSourceConfig:
    return GitHubSourceConfig(
        owner=owner,
        repo=repo,
        events=events or ["issues", "pull_requests"],
        labels_filter=labels_filter or [],
        poll_interval=poll_interval,
        state=state,
    )


def _make_adaptor(token: str = "ghp_test123") -> GitHubAdaptor:
    """Create a GitHubAdaptor with a callback that collects emitted envelopes."""
    adaptor = GitHubAdaptor(token=token)
    adaptor._collected: list[Envelope] = []

    async def _collect(envelope: Envelope) -> None:
        adaptor._collected.append(envelope)  # type: ignore[attr-defined]

    adaptor.set_callback(_collect)
    return adaptor


def _setup_client(adaptor: GitHubAdaptor) -> None:
    """Manually create the httpx client (avoids spawning the background poll loop)."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if adaptor._token:
        headers["Authorization"] = f"Bearer {adaptor._token}"
    adaptor._client = httpx.AsyncClient(
        base_url=GITHUB_API,
        headers=headers,
        timeout=30.0,
    )
    adaptor._running = True


async def _teardown_client(adaptor: GitHubAdaptor) -> None:
    """Clean up a manually created client."""
    adaptor._running = False
    if adaptor._client:
        await adaptor._client.aclose()
        adaptor._client = None


# ===========================================================================
# normalize
# ===========================================================================


class TestNormalize:
    """Tests for GitHubAdaptor.normalize()."""

    @pytest.mark.asyncio
    async def test_normalize_issue(self):
        adaptor = _make_adaptor()
        raw = _make_issue(number=42, title="Login fails", body="Stack trace here")

        envelope = await adaptor.normalize(raw)

        assert envelope.source == "github"
        assert envelope.source_id == "acme/app#42"
        assert envelope.title == "[issue] Login fails"
        assert "Stack trace here" in envelope.body
        assert envelope.status == EnvelopeStatus.PENDING
        assert "issue" in envelope.labels
        assert "open" in envelope.labels
        assert envelope.priority == 1
        assert envelope.metadata["repo"] == "acme/app"
        assert envelope.metadata["number"] == 42
        assert envelope.metadata["kind"] == "issue"
        assert envelope.metadata["user"] == "alice"
        assert envelope.metadata["html_url"] == "https://github.com/acme/app/issues/42"

    @pytest.mark.asyncio
    async def test_normalize_pr(self):
        adaptor = _make_adaptor()
        raw = _make_pr(number=7, title="Add dark mode", merged=False, draft=True)

        envelope = await adaptor.normalize(raw)

        assert envelope.source_id == "acme/app#7"
        assert envelope.title == "[PR] Add dark mode"
        assert "PR state: open" in envelope.body
        assert "Draft: True" in envelope.body
        assert "pr" in envelope.labels
        assert envelope.metadata["kind"] == "PR"
        assert envelope.metadata["html_url"] == "https://github.com/acme/app/pull/7"

    @pytest.mark.asyncio
    async def test_normalize_merged_pr(self):
        adaptor = _make_adaptor()
        raw = _make_pr(state="closed", merged=True)

        envelope = await adaptor.normalize(raw)

        assert "Status: merged" in envelope.body
        assert "closed" in envelope.labels

    @pytest.mark.asyncio
    async def test_normalize_bug_priority(self):
        adaptor = _make_adaptor()
        raw = _make_issue(labels=[{"name": "bug"}, {"name": "P0"}])

        envelope = await adaptor.normalize(raw)

        assert "bug" in envelope.labels
        assert "P0" in envelope.labels
        assert envelope.priority == 2

    @pytest.mark.asyncio
    async def test_normalize_issue_with_no_body(self):
        adaptor = _make_adaptor()
        raw = _make_issue(body=None)

        envelope = await adaptor.normalize(raw)

        assert envelope.body == ""

    @pytest.mark.asyncio
    async def test_normalize_preserves_assignees_and_milestone(self):
        adaptor = _make_adaptor()
        raw = _make_issue()
        raw["assignees"] = [{"login": "dev1"}, {"login": "dev2"}]
        raw["milestone"] = {"title": "v2.0"}

        envelope = await adaptor.normalize(raw)

        assert envelope.metadata["assignees"] == ["dev1", "dev2"]
        assert envelope.metadata["milestone"] == "v2.0"

    @pytest.mark.asyncio
    async def test_normalize_reactions_count(self):
        adaptor = _make_adaptor()
        raw = _make_issue()
        raw["reactions"] = {"total_count": 15}

        envelope = await adaptor.normalize(raw)

        assert envelope.metadata["reactions"] == 15

    @pytest.mark.asyncio
    async def test_normalize_no_reactions_key(self):
        adaptor = _make_adaptor()
        raw = _make_issue()
        del raw["reactions"]

        envelope = await adaptor.normalize(raw)

        assert envelope.metadata["reactions"] == 0


# ===========================================================================
# Source management
# ===========================================================================


class TestSourceManagement:
    """Tests for add_source / remove_source / cursor persistence."""

    def test_add_source_initializes_cursor(self):
        adaptor = _make_adaptor()
        adaptor.add_source(_source_config("owner", "myrepo"))

        assert "owner/myrepo" in adaptor._sources
        assert "owner/myrepo" in adaptor._cursors
        ts = adaptor._cursors["owner/myrepo"]
        assert ts.endswith("Z")

    def test_add_source_preserves_existing_cursor(self):
        adaptor = _make_adaptor()
        adaptor._cursors["acme/app"] = "2025-01-01T00:00:00Z"
        adaptor.add_source(_source_config())

        assert adaptor._cursors["acme/app"] == "2025-01-01T00:00:00Z"

    def test_remove_source(self):
        adaptor = _make_adaptor()
        adaptor.add_source(_source_config())
        adaptor._etags["acme/app"] = "abc123"

        adaptor.remove_source("acme", "app")

        assert "acme/app" not in adaptor._sources
        assert "acme/app" not in adaptor._cursors
        assert "acme/app" not in adaptor._etags

    def test_remove_source_nonexistent(self):
        adaptor = _make_adaptor()
        adaptor.remove_source("ghost", "repo")  # should not raise

    def test_get_restore_cursors(self):
        adaptor = _make_adaptor()
        adaptor.add_source(_source_config("a", "b"))
        adaptor.add_source(_source_config("c", "d"))

        cursors = adaptor.get_cursors()
        assert len(cursors) == 2
        assert "a/b" in cursors
        assert "c/d" in cursors

        adaptor2 = _make_adaptor()
        adaptor2.restore_cursors(cursors)
        assert adaptor2._cursors["a/b"] == cursors["a/b"]


# ===========================================================================
# Polling (_poll_source)
# ===========================================================================


class TestPollSource:
    """Tests for _poll_source with mocked HTTP.

    Uses _setup_client() to create the httpx client directly,
    avoiding the background poll loop from start().
    """

    @pytest.mark.asyncio
    async def test_poll_emits_envelopes(self):
        adaptor = _make_adaptor()
        config = _source_config(poll_interval=60)
        adaptor.add_source(config)
        adaptor._cursors["acme/app"] = "2025-06-01T00:00:00Z"

        issue = _make_issue(number=1, updated_at="2025-06-01T12:00:00Z")
        pr = _make_pr(number=2, updated_at="2025-06-01T13:00:00Z")

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(200, json=[issue, pr]),
            )
            _setup_client(adaptor)
            await adaptor._poll_source("acme/app", config)

        assert len(adaptor._collected) == 2
        assert adaptor._collected[0].source_id == "acme/app#1"
        assert adaptor._collected[1].source_id == "acme/app#2"
        assert adaptor._cursors["acme/app"] == "2025-06-01T13:00:00Z"

        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_poll_304_skips(self):
        adaptor = _make_adaptor()
        config = _source_config()
        adaptor.add_source(config)

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(304),
            )
            _setup_client(adaptor)
            await adaptor._poll_source("acme/app", config)

        assert len(adaptor._collected) == 0
        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_poll_etag_sent(self):
        adaptor = _make_adaptor()
        config = _source_config()
        adaptor.add_source(config)
        adaptor._etags["acme/app"] = '"abc123"'

        with respx.mock:
            route = respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(200, json=[]),
            )
            _setup_client(adaptor)
            await adaptor._poll_source("acme/app", config)

            request = route.calls[0].request
            assert request.headers.get("if-none-match") == '"abc123"'

        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_poll_saves_etag(self):
        adaptor = _make_adaptor()
        config = _source_config()
        adaptor.add_source(config)

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(
                    200,
                    json=[],
                    headers={"ETag": '"new-etag-456"'},
                ),
            )
            _setup_client(adaptor)
            await adaptor._poll_source("acme/app", config)

        assert adaptor._etags["acme/app"] == '"new-etag-456"'
        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_poll_dedup(self):
        """Same source_id seen on second poll should not produce a second envelope."""
        adaptor = _make_adaptor()
        config = _source_config()
        adaptor.add_source(config)
        adaptor._cursors["acme/app"] = "2025-06-01T00:00:00Z"

        issue = _make_issue(number=1, updated_at="2025-06-01T12:00:00Z")

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(200, json=[issue]),
            )
            _setup_client(adaptor)
            await adaptor._poll_source("acme/app", config)
            # Second poll returns the same item
            await adaptor._poll_source("acme/app", config)

        assert len(adaptor._collected) == 1
        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_poll_empty_response(self):
        adaptor = _make_adaptor()
        config = _source_config()
        adaptor.add_source(config)
        adaptor._cursors["acme/app"] = "2025-06-01T00:00:00Z"

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(200, json=[]),
            )
            _setup_client(adaptor)
            await adaptor._poll_source("acme/app", config)

        assert len(adaptor._collected) == 0
        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_poll_no_cursor_returns_early(self):
        adaptor = _make_adaptor()
        config = _source_config()
        adaptor.add_source(config)
        adaptor._cursors.pop("acme/app", None)

        _setup_client(adaptor)
        await adaptor._poll_source("acme/app", config)

        assert len(adaptor._collected) == 0
        await _teardown_client(adaptor)


# ===========================================================================
# Event type filtering
# ===========================================================================


class TestEventTypeFilter:
    @pytest.mark.asyncio
    async def test_issues_only(self):
        adaptor = _make_adaptor()
        config = _source_config(events=["issues"])
        adaptor.add_source(config)
        adaptor._cursors["acme/app"] = "2025-06-01T00:00:00Z"

        issue = _make_issue(number=1, updated_at="2025-06-01T12:00:00Z")
        pr = _make_pr(number=2, updated_at="2025-06-01T13:00:00Z")

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(200, json=[issue, pr]),
            )
            _setup_client(adaptor)
            await adaptor._poll_source("acme/app", config)

        assert len(adaptor._collected) == 1
        assert adaptor._collected[0].source_id == "acme/app#1"
        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_prs_only(self):
        adaptor = _make_adaptor()
        config = _source_config(events=["pull_requests"])
        adaptor.add_source(config)
        adaptor._cursors["acme/app"] = "2025-06-01T00:00:00Z"

        issue = _make_issue(number=1, updated_at="2025-06-01T12:00:00Z")
        pr = _make_pr(number=2, updated_at="2025-06-01T13:00:00Z")

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(200, json=[issue, pr]),
            )
            _setup_client(adaptor)
            await adaptor._poll_source("acme/app", config)

        assert len(adaptor._collected) == 1
        assert adaptor._collected[0].source_id == "acme/app#2"
        await _teardown_client(adaptor)


# ===========================================================================
# Label filtering
# ===========================================================================


class TestLabelFilter:
    @pytest.mark.asyncio
    async def test_label_filter_matches(self):
        adaptor = _make_adaptor()
        config = _source_config(labels_filter=["bug", "enhancement"])
        adaptor.add_source(config)
        adaptor._cursors["acme/app"] = "2025-06-01T00:00:00Z"

        issue = _make_issue(
            number=1,
            labels=[{"name": "bug"}],
            updated_at="2025-06-01T12:00:00Z",
        )

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(200, json=[issue]),
            )
            _setup_client(adaptor)
            await adaptor._poll_source("acme/app", config)

        assert len(adaptor._collected) == 1
        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_label_filter_no_match(self):
        adaptor = _make_adaptor()
        config = _source_config(labels_filter=["security"])
        adaptor.add_source(config)
        adaptor._cursors["acme/app"] = "2025-06-01T00:00:00Z"

        issue = _make_issue(
            number=1,
            labels=[{"name": "bug"}],
            updated_at="2025-06-01T12:00:00Z",
        )

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(200, json=[issue]),
            )
            _setup_client(adaptor)
            await adaptor._poll_source("acme/app", config)

        assert len(adaptor._collected) == 0
        await _teardown_client(adaptor)


# ===========================================================================
# Rate limiting
# ===========================================================================


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_403_rate_limit_backs_off(self):
        adaptor = _make_adaptor()
        config = _source_config(poll_interval=1)
        adaptor.add_source(config)

        future_ts = int(datetime.now(UTC).timestamp()) + 3600
        recorded_backoff: float = 0

        original_sleep = asyncio.sleep

        async def mock_sleep(seconds):
            nonlocal recorded_backoff
            if seconds > 100:
                recorded_backoff = seconds
                adaptor._running = False  # stop the loop
            else:
                await original_sleep(0)

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(
                    403,
                    headers={"X-RateLimit-Reset": str(future_ts)},
                    json={"message": "rate limit exceeded"},
                ),
            )
            _setup_client(adaptor)

            with pytest.MonkeyPatch.context() as m:
                m.setattr(asyncio, "sleep", mock_sleep)
                await adaptor._poll_loop()

        assert recorded_backoff >= 10  # max(., 10) floor
        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_non_403_error_continues(self):
        adaptor = _make_adaptor()
        config = _source_config(poll_interval=1)
        adaptor.add_source(config)

        real_sleep = asyncio.sleep

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                side_effect=httpx.HTTPStatusError(
                    "Server Error",
                    request=httpx.Request("GET", "https://api.github.com/repos/acme/app/issues"),
                    response=httpx.Response(500, json={"message": "internal error"}),
                ),
            )
            _setup_client(adaptor)

            # Stop after one iteration
            async def stop_soon():
                await real_sleep(0)
                adaptor._running = False

            with pytest.MonkeyPatch.context() as m:
                m.setattr(asyncio, "sleep", lambda _: real_sleep(0))
                await asyncio.gather(adaptor._poll_loop(), stop_soon())

        await _teardown_client(adaptor)


# ===========================================================================
# execute_action
# ===========================================================================


class TestExecuteAction:
    @pytest.mark.asyncio
    async def test_comment_action(self):
        adaptor = _make_adaptor()
        envelope = Envelope(
            source="github",
            source_id="acme/app#42",
            metadata={"repo": "acme/app", "number": 42},
        )

        with respx.mock:
            route = respx.post(f"{GITHUB_API}/repos/acme/app/issues/42/comments").mock(
                return_value=httpx.Response(201, json={"id": 1}),
            )
            _setup_client(adaptor)
            await adaptor.execute_action(envelope, {"type": "comment", "body": "LGTM!"})

            assert route.called
            body = json.loads(route.calls[0].request.read())
            assert body == {"body": "LGTM!"}

        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_close_action(self):
        adaptor = _make_adaptor()
        envelope = Envelope(
            source="github",
            source_id="acme/app#42",
            metadata={"repo": "acme/app", "number": 42},
        )

        with respx.mock:
            route = respx.patch(f"{GITHUB_API}/repos/acme/app/issues/42").mock(
                return_value=httpx.Response(200, json={"state": "closed"}),
            )
            _setup_client(adaptor)
            await adaptor.execute_action(envelope, {"type": "close"})

            assert route.called

        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_label_add_action(self):
        adaptor = _make_adaptor()
        envelope = Envelope(
            source="github",
            source_id="acme/app#42",
            metadata={"repo": "acme/app", "number": 42},
        )

        with respx.mock:
            route = respx.post(f"{GITHUB_API}/repos/acme/app/issues/42/labels").mock(
                return_value=httpx.Response(200, json=[]),
            )
            _setup_client(adaptor)
            await adaptor.execute_action(
                envelope,
                {"type": "label", "add": ["wontfix", "stale"]},
            )

            assert route.called

        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_label_remove_action(self):
        adaptor = _make_adaptor()
        envelope = Envelope(
            source="github",
            source_id="acme/app#42",
            metadata={"repo": "acme/app", "number": 42},
        )

        with respx.mock:
            r1 = respx.delete(f"{GITHUB_API}/repos/acme/app/issues/42/labels/bug").mock(
                return_value=httpx.Response(200, json=[])
            )
            r2 = respx.delete(f"{GITHUB_API}/repos/acme/app/issues/42/labels/help-wanted").mock(
                return_value=httpx.Response(200, json=[])
            )

            _setup_client(adaptor)
            await adaptor.execute_action(
                envelope,
                {"type": "label", "remove": ["bug", "help-wanted"]},
            )

            assert r1.called
            assert r2.called

        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_unknown_action_type(self):
        adaptor = _make_adaptor()
        envelope = Envelope(
            source="github",
            source_id="acme/app#42",
            metadata={"repo": "acme/app", "number": 42},
        )

        with respx.mock:
            _setup_client(adaptor)
            await adaptor.execute_action(envelope, {"type": "merge"})
            # No crash

        await _teardown_client(adaptor)


# ===========================================================================
# Lifecycle
# ===========================================================================


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_without_sources_is_noop(self):
        adaptor = _make_adaptor()
        await adaptor.start()
        assert not adaptor.is_running
        assert adaptor._client is None

    @pytest.mark.asyncio
    async def test_start_creates_client_with_auth(self):
        adaptor = _make_adaptor(token="ghp_secret")
        adaptor.add_source(_source_config())

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(200, json=[]),
            )
            await adaptor.start()
            await asyncio.sleep(0.1)  # let poll loop tick once

        assert adaptor.is_running
        assert adaptor._client is not None
        auth = adaptor._client.headers.get("authorization", "")
        assert "Bearer ghp_secret" in auth

        await adaptor.stop()
        assert not adaptor.is_running

    @pytest.mark.asyncio
    async def test_start_no_token_no_auth_header(self):
        adaptor = GitHubAdaptor(token="")
        adaptor.set_callback(lambda e: asyncio.sleep(0))
        adaptor.add_source(_source_config())

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(200, json=[]),
            )
            await adaptor.start()
            await asyncio.sleep(0.1)

        assert adaptor._client is not None
        header_keys = {k.lower() for k in adaptor._client.headers.keys()}
        assert "authorization" not in header_keys

        await adaptor.stop()

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self):
        adaptor = _make_adaptor()
        adaptor.add_source(_source_config())

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(200, json=[]),
            )
            await adaptor.start()
            assert adaptor.is_running
            await adaptor.stop()

        assert not adaptor.is_running
        assert adaptor._client is None
        assert adaptor._poll_task is None


# ===========================================================================
# Cursor advancement
# ===========================================================================


class TestCursorAdvancement:
    @pytest.mark.asyncio
    async def test_cursor_advances_to_latest(self):
        adaptor = _make_adaptor()
        config = _source_config()
        adaptor.add_source(config)
        adaptor._cursors["acme/app"] = "2025-06-01T00:00:00Z"

        items = [
            _make_issue(number=1, updated_at="2025-06-01T10:00:00Z"),
            _make_issue(number=2, updated_at="2025-06-01T11:00:00Z"),
            _make_pr(number=3, updated_at="2025-06-01T15:00:00Z"),
        ]

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(200, json=items),
            )
            _setup_client(adaptor)
            await adaptor._poll_source("acme/app", config)

        assert adaptor._cursors["acme/app"] == "2025-06-01T15:00:00Z"
        await _teardown_client(adaptor)

    @pytest.mark.asyncio
    async def test_cursor_stays_when_no_newer_items(self):
        adaptor = _make_adaptor()
        config = _source_config()
        adaptor.add_source(config)
        adaptor._cursors["acme/app"] = "2025-06-01T20:00:00Z"

        items = [
            _make_issue(number=1, updated_at="2025-06-01T10:00:00Z"),
        ]

        with respx.mock:
            respx.get(f"{GITHUB_API}/repos/acme/app/issues").mock(
                return_value=httpx.Response(200, json=items),
            )
            _setup_client(adaptor)
            await adaptor._poll_source("acme/app", config)

        assert adaptor._cursors["acme/app"] == "2025-06-01T20:00:00Z"
        await _teardown_client(adaptor)
