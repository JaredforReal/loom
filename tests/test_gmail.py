"""Tests for ``loom.adaptor.gmail``.

These tests stub out ``googleapiclient`` and OAuth entirely — no network. They
cover the helpers (`_extract_header`, `_walk_parts`, `_decode_body`),
`normalize`, the seen-set persistence, `_poll_once`, and `execute_action`.
"""

from __future__ import annotations

import asyncio
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
from loom.core.eventbus import EventBus
from loom.core.mailbox import Mailbox
from loom.state.store import Store

# -- fixtures ------------------------------------------------------------------


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
    bus = EventBus()
    store = Store()
    mailbox = Mailbox(store, bus)
    return GmailAdaptor(
        mailbox=mailbox,
        client_secrets_path=tmp_path / "client-secrets.json",
        token_path=tmp_path / "token.json",
        state_path=tmp_path / "state.json",
        poll_seconds=1,
    )


# -- helpers -------------------------------------------------------------------


def test_extract_header_is_case_insensitive() -> None:
    headers: list[dict[str, str]] = [
        {"name": "Subject", "value": "Hi"},
        {"name": "FROM", "value": "a@b"},
    ]
    assert _extract_header(headers, "subject") == "Hi"  # type: ignore[arg-type]
    assert _extract_header(headers, "From") == "a@b"  # type: ignore[arg-type]


def test_extract_header_missing_returns_empty() -> None:
    assert _extract_header([], "Subject") == ""


def test_walk_parts_recurses_through_multipart() -> None:
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


def test_decode_body_prefers_text_plain() -> None:
    payload = _make_payload(plain="hello plain", html="<b>hello html</b>")
    assert _decode_body(payload) == "hello plain"


def test_decode_body_falls_back_to_html_when_plain_missing() -> None:
    payload = _make_payload(plain=None, html="<b>only html</b>")
    assert _decode_body(payload) == "<b>only html</b>"


def test_decode_body_returns_empty_when_no_part_has_data() -> None:
    payload: dict[str, Any] = {
        "mimeType": "text/plain",
        "body": {},
        "parts": [],
    }
    assert _decode_body(payload) == ""


def test_decode_body_handles_unicode() -> None:
    payload = _make_payload(plain="你好，世界 🌏")
    assert _decode_body(payload) == "你好，世界 🌏"


# -- normalize -----------------------------------------------------------------


async def test_normalize_basic_text_email(tmp_path: Path) -> None:
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


async def test_normalize_html_only(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    env = await ad.normalize(_make_message(plain=None, html="<p>html only</p>"))
    assert env.body == "<p>html only</p>"


async def test_normalize_detects_attachment(tmp_path: Path) -> None:
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


async def test_normalize_invalid_internal_date_does_not_raise(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    msg = _make_message()
    msg["internalDate"] = "not-a-number"
    env = await ad.normalize(msg)
    assert env.received_at is not None


async def test_normalize_missing_optional_headers(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    msg = _make_message(headers=[{"name": "Subject", "value": "S"}])
    env = await ad.normalize(msg)
    assert env.title == "S"
    assert env.metadata["from"] == ""
    assert env.metadata["in_reply_to"] == ""


# -- seen-set persistence ------------------------------------------------------


def test_record_seen_dedupes(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    ad._record_seen("a")
    ad._record_seen("a")
    assert len(ad._seen) == 1
    assert ad._seen_index == {"a"}


def test_record_seen_evicts_oldest_at_max(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    overflow = 5
    for i in range(SEEN_SET_MAX + overflow):
        ad._record_seen(f"id-{i}")
    assert len(ad._seen) == SEEN_SET_MAX
    assert "id-0" not in ad._seen_index
    assert f"id-{SEEN_SET_MAX + overflow - 1}" in ad._seen_index


def test_load_seen_when_no_state_file(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    ad._load_seen()  # must not raise
    assert ad._seen_index == set()


def test_load_seen_when_corrupt_json(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    ad._state_path.parent.mkdir(parents=True, exist_ok=True)
    ad._state_path.write_text("not valid json {")
    ad._load_seen()
    assert ad._seen_index == set()


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    ad._record_seen("x")
    ad._record_seen("y")
    ad._save_seen()

    fresh = _build_adaptor(tmp_path)
    fresh._load_seen()
    assert fresh._seen_index == {"x", "y"}


# -- execute_action ------------------------------------------------------------


async def test_execute_action_raises_when_not_started(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    env = Envelope(source="gmail", source_id="x")
    with pytest.raises(RuntimeError, match="not started"):
        await ad.execute_action(env, {"type": "reply", "body": "hi"})


async def test_execute_action_unknown_type(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    ad._service = MagicMock()
    env = Envelope(source="gmail", source_id="x")
    with pytest.raises(ValueError, match="Unknown gmail action type"):
        await ad.execute_action(env, {"type": "fly_to_moon"})


async def test_execute_action_reply_threads_correctly(tmp_path: Path) -> None:
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


async def test_execute_action_reply_does_not_double_re_prefix(tmp_path: Path) -> None:
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


async def test_execute_action_reply_explicit_to_overrides_from(tmp_path: Path) -> None:
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


async def test_execute_action_archive_removes_inbox_label(tmp_path: Path) -> None:
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


async def test_execute_action_label_adds_labels(tmp_path: Path) -> None:
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


async def test_execute_action_trash(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    service = MagicMock()
    ad._service = service
    env = Envelope(source="gmail", source_id="msg-1")
    await ad.execute_action(env, {"type": "trash"})
    service.users.return_value.messages.return_value.trash.assert_called_once_with(
        userId="me", id="msg-1"
    )


# -- _poll_once ---------------------------------------------------------------


async def test_poll_ingests_new_messages_and_records_seen(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    received: list[Envelope] = []

    async def capture(_event: str, env: object) -> None:
        if isinstance(env, Envelope):
            received.append(env)

    ad._mailbox._bus.subscribe("new_envelope", capture)

    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "a"}, {"id": "b"}],
    }
    fetched = {"a": _make_message("a"), "b": _make_message("b")}

    def get_call(*, userId: str, id: str, format: str) -> Any:  # noqa: N803 (real Gmail API param)
        del userId, format
        m = MagicMock()
        m.execute.return_value = fetched[id]
        return m

    service.users.return_value.messages.return_value.get.side_effect = get_call
    ad._service = service

    await ad._poll_once()
    # Let bus.publish's create_task callbacks run.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert {e.source_id for e in received} == {"a", "b"}
    assert {"a", "b"} <= ad._seen_index


async def test_poll_skips_already_seen(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    ad._record_seen("a")

    received: list[Envelope] = []

    async def capture(_event: str, env: object) -> None:
        if isinstance(env, Envelope):
            received.append(env)

    ad._mailbox._bus.subscribe("new_envelope", capture)

    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "a"}],
    }
    ad._service = service

    await ad._poll_once()
    await asyncio.sleep(0)

    assert received == []
    assert not service.users.return_value.messages.return_value.get.called


async def test_poll_swallows_http_error_on_list(tmp_path: Path) -> None:
    from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

    ad = _build_adaptor(tmp_path)
    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.side_effect = (
        HttpError(resp=MagicMock(status=500, reason="oops"), content=b"server err")
    )
    ad._service = service

    # Must not raise — adaptor logs and waits for next poll.
    await ad._poll_once()


async def test_poll_continues_when_one_message_fails(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    received: list[Envelope] = []

    async def capture(_event: str, env: object) -> None:
        if isinstance(env, Envelope):
            received.append(env)

    ad._mailbox._bus.subscribe("new_envelope", capture)

    service = MagicMock()
    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        "messages": [{"id": "bad"}, {"id": "good"}],
    }

    def get_call(*, userId: str, id: str, format: str) -> Any:  # noqa: N803 (real Gmail API param)
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
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert {e.source_id for e in received} == {"good"}
    assert "good" in ad._seen_index
    assert "bad" not in ad._seen_index


async def test_poll_does_nothing_when_service_unset(tmp_path: Path) -> None:
    ad = _build_adaptor(tmp_path)
    # _service is None until start() runs — should be a no-op.
    await ad._poll_once()
