"""Tests for ``loom.adaptor.gmail``.

These tests stub out ``googleapiclient`` and OAuth entirely — no network. They
cover the helpers (`_extract_header`, `_walk_parts`, `_decode_body`),
`normalize`, the seen-set export/restore API, `_poll_once`, and `execute_action`.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from loom.adaptor.gmail import (
    SEEN_SET_MAX,
    GmailAdaptor,
    _decode_body,
    _extract_header,
    _walk_parts,
)
from loom.core.envelope import Envelope

# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _make_payload(
    plain: str | None = "Body text",
    html: str | None = None,
    headers: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    if plain is not None:
        parts.append({"mimeType": "text/plain", "body": {"data": _b64(plain)}})
    if html is not None:
        parts.append({"mimeType": "text/html", "body": {"data": _b64(html)}})
    return {
        "mimeType": "multipart/alternative",
        "headers": headers
        or [
            {"name": "Subject", "value": "Hello"},
            {"name": "From", "value": "Alice <alice@example.com>"},
            {"name": "To", "value": "me@example.com"},
            {"name": "Message-ID", "value": "<msg@example.com>"},
        ],
        "parts": parts,
    }


def _make_message(
    msg_id: str = "abc",
    thread_id: str = "thread-1",
    *,
    plain: str | None = "Body text",
    html: str | None = None,
    labels: list[str] | None = None,
    internal_ms: int = 1_700_000_000_000,
    headers: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "id": msg_id,
        "threadId": thread_id,
        "labelIds": labels if labels is not None else ["INBOX", "UNREAD"],
        "snippet": "snippet text",
        "internalDate": str(internal_ms),
        "payload": _make_payload(plain=plain, html=html, headers=headers),
    }


def _build_adaptor(tmp_path: Path) -> GmailAdaptor:
    return GmailAdaptor(
        client_secrets_path=tmp_path / "client-secrets.json",
        token_path=tmp_path / "token.json",
        poll_seconds=1,
    )


def _build_adaptor_with_recorder(
    tmp_path: Path,
) -> tuple[GmailAdaptor, list[Envelope]]:
    """Build an adaptor with a callback that records emitted envelopes."""
    ad = _build_adaptor(tmp_path)
    received: list[Envelope] = []

    async def recorder(env: Envelope) -> None:
        received.append(env)

    ad.set_callback(recorder)
    return ad, received


# ===========================================================================
# Helpers
# ===========================================================================


class TestHelpers:
    """Tests for module-level helpers: _extract_header, _walk_parts, _decode_body."""

    def test_extract_header_is_case_insensitive(self):
        headers: list[dict[str, str]] = [
            {"name": "Subject", "value": "Hi"},
            {"name": "FROM", "value": "a@b"},
        ]
        assert _extract_header(headers, "subject") == "Hi"  # type: ignore[arg-type]
        assert _extract_header(headers, "From") == "a@b"  # type: ignore[arg-type]

    def test_extract_header_missing_returns_empty(self):
        assert _extract_header([], "Subject") == ""

    def test_walk_parts_recurses_through_multipart(self):
        payload: dict[str, Any] = {
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "text/plain"},
                {
                    "mimeType": "multipart/alternative",
                    "parts": [{"mimeType": "text/html"}],
                },
            ],
        }
        seen = list(_walk_parts(payload))
        # root + plain + nested-multipart + html
        assert len(seen) == 4
        assert seen[0] is payload

    def test_decode_body_prefers_text_plain(self):
        payload = _make_payload(plain="hello plain", html="<b>hello html</b>")
        assert _decode_body(payload) == "hello plain"

    def test_decode_body_falls_back_to_html_when_plain_missing(self):
        payload = _make_payload(plain=None, html="<b>only html</b>")
        assert _decode_body(payload) == "<b>only html</b>"

    def test_decode_body_returns_empty_when_no_part_has_data(self):
        payload: dict[str, Any] = {
            "mimeType": "text/plain",
            "body": {},
            "parts": [],
        }
        assert _decode_body(payload) == ""

    def test_decode_body_handles_unicode(self):
        payload = _make_payload(plain="你好，世界 🌏")
        assert _decode_body(payload) == "你好，世界 🌏"


# ===========================================================================
# Normalize
# ===========================================================================


class TestNormalize:
    """Tests for GmailAdaptor.normalize()."""

    @pytest.mark.asyncio
    async def test_normalize_basic_text_email(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        env = await ad.normalize(_make_message())
        assert env.source == "gmail"
        assert env.source_id == "abc"
        assert env.title == "Hello"
        assert env.body == "Body text"
        assert env.labels == ["INBOX", "UNREAD"]
        assert env.metadata["thread_id"] == "thread-1"
        assert env.metadata["from"] == "Alice <alice@example.com>"
        assert env.metadata["message_id_header"] == "<msg@example.com>"
        assert env.metadata["has_attachments"] is False

    @pytest.mark.asyncio
    async def test_normalize_html_only(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        env = await ad.normalize(_make_message(plain=None, html="<p>html only</p>"))
        assert env.body == "<p>html only</p>"

    @pytest.mark.asyncio
    async def test_normalize_detects_attachment(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        msg = _make_message()
        msg["payload"]["parts"].append(
            {
                "mimeType": "application/pdf",
                "filename": "report.pdf",
                "body": {"size": 1234},
            }
        )
        env = await ad.normalize(msg)
        assert env.metadata["has_attachments"] is True

    @pytest.mark.asyncio
    async def test_normalize_invalid_internal_date_does_not_raise(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        msg = _make_message()
        msg["internalDate"] = "not-a-number"
        env = await ad.normalize(msg)
        assert env.received_at is not None

    @pytest.mark.asyncio
    async def test_normalize_missing_optional_headers(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        msg = _make_message(headers=[{"name": "Subject", "value": "S"}])
        env = await ad.normalize(msg)
        assert env.title == "S"
        assert env.metadata["from"] == ""
        assert env.metadata["in_reply_to"] == ""


# ===========================================================================
# Seen-set
# ===========================================================================


class TestSeenSet:
    """Tests for _record_seen, export_seen, and restore_seen."""

    def test_record_seen_dedupes(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        ad._record_seen("a")
        ad._record_seen("a")
        assert len(ad._seen) == 1
        assert ad._seen_index == {"a"}

    def test_record_seen_evicts_oldest_at_max(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        overflow = 5
        for i in range(SEEN_SET_MAX + overflow):
            ad._record_seen(f"id-{i}")
        assert len(ad._seen) == SEEN_SET_MAX
        assert "id-0" not in ad._seen_index
        assert f"id-{SEEN_SET_MAX + overflow - 1}" in ad._seen_index

    def test_restore_seen_empty(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        ad.restore_seen([])
        assert ad._seen_index == set()

    def test_restore_seen_ignores_non_strings(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        ad.restore_seen(["a", 123, None, "b"])  # type: ignore[list-item]
        assert ad._seen_index == {"a", "b"}

    def test_export_restore_roundtrip(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        ad._record_seen("x")
        ad._record_seen("y")
        snapshot = ad.export_seen()
        assert snapshot == ["x", "y"]

        fresh = _build_adaptor(tmp_path)
        fresh.restore_seen(snapshot)
        assert fresh._seen_index == {"x", "y"}


# ===========================================================================
# Execute actions
# ===========================================================================


class TestExecuteAction:
    """Tests for GmailAdaptor.execute_action()."""

    @pytest.mark.asyncio
    async def test_raises_when_not_started(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        env = Envelope(source="gmail", source_id="x")
        with pytest.raises(RuntimeError, match="not started"):
            await ad.execute_action(env, {"type": "reply", "body": "hi"})

    @pytest.mark.asyncio
    async def test_unknown_type(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        ad._service = MagicMock()
        env = Envelope(source="gmail", source_id="x")
        with pytest.raises(ValueError, match="Unknown gmail action type"):
            await ad.execute_action(env, {"type": "fly_to_moon"})

    @pytest.mark.asyncio
    async def test_reply_threads_correctly(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        service = MagicMock()
        ad._service = service

        env = Envelope(
            source="gmail",
            source_id="msg-1",
            title="Project update",
            metadata={
                "thread_id": "thread-xyz",
                "message_id_header": "<orig@example.com>",
                "references": "<ref1@example.com>",
                "from": "Bob <bob@example.com>",
            },
        )
        await ad.execute_action(env, {"type": "reply", "body": "Hi back"})

        send = service.users.return_value.messages.return_value.send
        send.assert_called_once()
        body = send.call_args.kwargs["body"]
        assert body["threadId"] == "thread-xyz"
        raw = base64.urlsafe_b64decode(body["raw"]).decode("utf-8")
        assert "To: bob@example.com" in raw
        assert "Subject: Re: Project update" in raw
        assert "In-Reply-To: <orig@example.com>" in raw
        assert "References: <ref1@example.com> <orig@example.com>" in raw
        assert "Hi back" in raw

    @pytest.mark.asyncio
    async def test_reply_does_not_double_re_prefix(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        ad._service = MagicMock()
        env = Envelope(
            source="gmail",
            source_id="msg-1",
            title="Re: Already a reply",
            metadata={"from": "bob@example.com", "thread_id": "t"},
        )
        await ad.execute_action(env, {"type": "reply", "body": "ack"})
        send = ad._service.users.return_value.messages.return_value.send
        raw = base64.urlsafe_b64decode(send.call_args.kwargs["body"]["raw"]).decode("utf-8")
        assert "Subject: Re: Already a reply" in raw
        assert "Subject: Re: Re:" not in raw

    @pytest.mark.asyncio
    async def test_reply_explicit_to_overrides_from(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        ad._service = MagicMock()
        env = Envelope(
            source="gmail",
            source_id="msg-1",
            metadata={"from": "noreply@example.com"},
        )
        await ad.execute_action(env, {"type": "reply", "body": "ok", "to": "human@example.com"})
        send = ad._service.users.return_value.messages.return_value.send
        raw = base64.urlsafe_b64decode(send.call_args.kwargs["body"]["raw"]).decode("utf-8")
        assert "To: human@example.com" in raw

    @pytest.mark.asyncio
    async def test_archive_removes_inbox_label(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        service = MagicMock()
        ad._service = service
        env = Envelope(source="gmail", source_id="msg-1")
        await ad.execute_action(env, {"type": "archive"})
        service.users.return_value.messages.return_value.modify.assert_called_once_with(
            userId="me",
            id="msg-1",
            body={"addLabelIds": [], "removeLabelIds": ["INBOX"]},
        )

    @pytest.mark.asyncio
    async def test_label_adds_labels(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        service = MagicMock()
        ad._service = service
        env = Envelope(source="gmail", source_id="msg-1")
        await ad.execute_action(env, {"type": "label", "labels": ["IMPORTANT", "STARRED"]})
        service.users.return_value.messages.return_value.modify.assert_called_once_with(
            userId="me",
            id="msg-1",
            body={"addLabelIds": ["IMPORTANT", "STARRED"], "removeLabelIds": []},
        )

    @pytest.mark.asyncio
    async def test_trash(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        service = MagicMock()
        ad._service = service
        env = Envelope(source="gmail", source_id="msg-1")
        await ad.execute_action(env, {"type": "trash"})
        service.users.return_value.messages.return_value.trash.assert_called_once_with(
            userId="me", id="msg-1"
        )


# ===========================================================================
# Polling
# ===========================================================================


class TestPolling:
    """Tests for GmailAdaptor._poll_once()."""

    @pytest.mark.asyncio
    async def test_ingests_new_messages_and_records_seen(self, tmp_path):
        ad, received = _build_adaptor_with_recorder(tmp_path)

        service = MagicMock()
        service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "a"}, {"id": "b"}],
        }
        fetched = {"a": _make_message("a"), "b": _make_message("b")}

        def get_call(*, userId: str, id: str, format: str) -> Any:  # noqa: N803 (Gmail API param)
            del userId, format
            m = MagicMock()
            m.execute.return_value = fetched[id]
            return m

        service.users.return_value.messages.return_value.get.side_effect = get_call
        ad._service = service

        await ad._poll_once()

        assert {e.source_id for e in received} == {"a", "b"}
        assert {"a", "b"} <= ad._seen_index

    @pytest.mark.asyncio
    async def test_skips_already_seen(self, tmp_path):
        ad, received = _build_adaptor_with_recorder(tmp_path)
        ad._record_seen("a")

        service = MagicMock()
        service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "a"}],
        }
        ad._service = service

        await ad._poll_once()

        assert received == []
        assert not service.users.return_value.messages.return_value.get.called

    @pytest.mark.asyncio
    async def test_swallows_http_error_on_list(self, tmp_path):
        from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

        ad = _build_adaptor(tmp_path)
        service = MagicMock()
        service.users.return_value.messages.return_value.list.return_value.execute.side_effect = (
            HttpError(resp=MagicMock(status=500, reason="oops"), content=b"server err")
        )
        ad._service = service

        # Must not raise — adaptor logs and waits for next poll.
        await ad._poll_once()

    @pytest.mark.asyncio
    async def test_continues_when_one_message_fails(self, tmp_path):
        ad, received = _build_adaptor_with_recorder(tmp_path)

        service = MagicMock()
        service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
            "messages": [{"id": "bad"}, {"id": "good"}],
        }

        def get_call(*, userId: str, id: str, format: str) -> Any:  # noqa: N803 (Gmail API param)
            del userId, format
            m = MagicMock()
            if id == "bad":
                m.execute.side_effect = RuntimeError("bad message")
            else:
                m.execute.return_value = _make_message("good")
            return m

        service.users.return_value.messages.return_value.get.side_effect = get_call
        ad._service = service

        await ad._poll_once()

        assert {e.source_id for e in received} == {"good"}
        assert "good" in ad._seen_index
        assert "bad" not in ad._seen_index

    @pytest.mark.asyncio
    async def test_does_nothing_when_service_unset(self, tmp_path):
        ad = _build_adaptor(tmp_path)
        # _service is None until start() runs — should be a no-op.
        await ad._poll_once()
