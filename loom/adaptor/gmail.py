"""Gmail adaptor — Google API REST + OAuth2.

Polls Gmail for new messages matching a query, normalises them into
``Envelope`` objects, and delivers them via ``BaseAdaptor._emit`` to
whatever callback the orchestrator has installed. Approved actions
supported: ``reply`` / ``archive`` / ``label`` / ``trash``.
"""

from __future__ import annotations

import base64
import logging
from collections import deque
from collections.abc import Iterable
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Any, TypedDict, cast

import anyio
import httplib2  # type: ignore[import-untyped]
from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from loom.adaptor.base import BaseAdaptor
from loom.core.envelope import Envelope

logger = logging.getLogger(__name__)


SCOPES: list[str] = ["https://www.googleapis.com/auth/gmail.modify"]
DEFAULT_QUERY = "is:unread -in:chats newer_than:1d"
DEFAULT_POLL_SECONDS = 30
SEEN_SET_MAX = 1000

_CREDENTIALS_DIR = Path.home() / ".loom" / "credentials"
DEFAULT_TOKEN_PATH = _CREDENTIALS_DIR / "gmail-token.json"


# Typed views over the bits of Google's JSON we touch. The Gmail API returns
# plenty more fields; only model what we read so mypy keeps us honest.


class GmailHeader(TypedDict):
    name: str
    value: str


class GmailPayload(TypedDict, total=False):
    mimeType: str
    headers: list[GmailHeader]
    body: dict[str, Any]
    parts: list[dict[str, Any]]
    filename: str


class GmailMessage(TypedDict, total=False):
    id: str
    threadId: str
    labelIds: list[str]
    snippet: str
    internalDate: str
    payload: GmailPayload


def _extract_header(headers: list[GmailHeader], name: str) -> str:
    target = name.lower()
    for h in headers:
        if h.get("name", "").lower() == target:
            return h.get("value", "")
    return ""


def _walk_parts(part: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield part
    for sub in part.get("parts") or []:
        yield from _walk_parts(sub)


def _decode_body(payload: dict[str, Any]) -> str:
    """Return the most-text-friendly body we can find; prefer text/plain."""
    plain = ""
    html = ""
    for part in _walk_parts(payload):
        mime = part.get("mimeType", "")
        body = part.get("body") or {}
        data = body.get("data")
        if not data:
            continue
        try:
            decoded = base64.urlsafe_b64decode(data.encode("ascii")).decode(
                "utf-8", errors="replace"
            )
        except (ValueError, UnicodeDecodeError):
            continue
        if mime == "text/plain" and not plain:
            plain = decoded
        elif mime == "text/html" and not html:
            html = decoded
    return plain or html


def _build_http(proxy_url: str | None) -> Any:
    if proxy_url is None:
        return httplib2.Http()
    # Minimal parsing: scheme://host:port
    try:
        from urllib.parse import urlparse

        parsed = urlparse(proxy_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8080
        if parsed.scheme in ("http", "https"):
            proxy_type = httplib2.socks.PROXY_TYPE_HTTP
        elif parsed.scheme == "socks5":
            proxy_type = httplib2.socks.PROXY_TYPE_SOCKS5
        elif parsed.scheme == "socks4":
            proxy_type = httplib2.socks.PROXY_TYPE_SOCKS4
        else:
            logger.warning("Unsupported proxy scheme %s, using no proxy", parsed.scheme)
            return httplib2.Http()
        return httplib2.Http(proxy_info=httplib2.ProxyInfo(proxy_type, host, port))
    except Exception:
        logger.warning("Failed to parse proxy_url %s, using no proxy", proxy_url)
        return httplib2.Http()


def _load_credentials(client_secrets: Path, token_path: Path) -> Any:
    """Run InstalledAppFlow on first call, refresh thereafter."""
    creds: Any = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
            str(token_path), SCOPES
        )
    if creds is not None and creds.valid:
        return creds
    if creds is not None and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
        creds = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(cast(str, creds.to_json()))
    return creds


class GmailAdaptor(BaseAdaptor):
    """Polls Gmail via the Google API and emits Envelopes through ``_emit``."""

    name = "gmail"

    def __init__(
        self,
        client_secrets_path: Path,
        token_path: Path | None = None,
        query: str = DEFAULT_QUERY,
        poll_seconds: int = DEFAULT_POLL_SECONDS,
        user_id: str = "me",
        proxy_url: str | None = None,
    ) -> None:
        self._client_secrets = client_secrets_path
        self._token_path = token_path or DEFAULT_TOKEN_PATH
        self._query = query
        self._poll_seconds = poll_seconds
        self._user_id = user_id
        self._proxy_url = proxy_url

        self._service: Any = None
        self._scheduler: AsyncIOScheduler | None = None
        self._seen: deque[str] = deque(maxlen=SEEN_SET_MAX)
        self._seen_index: set[str] = set()
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Authenticate, build the Gmail service, and schedule the poll loop."""
        creds = await anyio.to_thread.run_sync(
            _load_credentials, self._client_secrets, self._token_path
        )
        http = await anyio.to_thread.run_sync(_build_http, self._proxy_url)
        self._service = await anyio.to_thread.run_sync(
            lambda: build("gmail", "v1", credentials=creds, http=http, cache_discovery=False)
        )

        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self._poll_once,
            "interval",
            seconds=self._poll_seconds,
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        self._running = True
        logger.info("GmailAdaptor started — polling every %ds", self._poll_seconds)

    async def stop(self) -> None:
        """Stop the scheduler and drop the API client."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        self._service = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def _poll_once(self) -> None:
        if self._service is None:
            return
        try:
            listing = await anyio.to_thread.run_sync(self._list_message_ids)
        except HttpError as exc:
            logger.error("Gmail list failed: %s", exc)
            return

        new_ids = [mid for mid in listing if mid not in self._seen_index]
        if not new_ids:
            return

        for mid in new_ids:
            try:
                raw = await anyio.to_thread.run_sync(self._fetch_message, mid)
                envelope = await self.normalize(raw)
                await self._emit(envelope)
                self._record_seen(mid)
            except Exception:
                logger.exception("Failed to ingest gmail message %s", mid)

    def _list_message_ids(self) -> list[str]:
        resp = self._service.users().messages().list(userId=self._user_id, q=self._query).execute()
        out: list[str] = []
        for entry in resp.get("messages") or []:
            mid = entry.get("id")
            if isinstance(mid, str):
                out.append(mid)
        return out

    def _fetch_message(self, message_id: str) -> GmailMessage:
        msg = (
            self._service.users()
            .messages()
            .get(userId=self._user_id, id=message_id, format="full")
            .execute()
        )
        return cast(GmailMessage, msg)

    # ------------------------------------------------------------------
    # Normalize
    # ------------------------------------------------------------------

    async def normalize(self, raw_event: Any) -> Envelope:
        """Convert a Gmail message dict into an ``Envelope``."""
        msg = cast(GmailMessage, raw_event)
        payload = cast(dict[str, Any], msg.get("payload", {}) or {})
        headers = cast(list[GmailHeader], payload.get("headers", []) or [])

        subject = _extract_header(headers, "Subject")
        from_hdr = _extract_header(headers, "From")
        to_hdr = _extract_header(headers, "To")
        cc_hdr = _extract_header(headers, "Cc")
        message_id_hdr = _extract_header(headers, "Message-ID")
        in_reply_to = _extract_header(headers, "In-Reply-To")
        references = _extract_header(headers, "References")

        body = _decode_body(payload)

        internal_ms_raw = msg.get("internalDate", "0") or "0"
        try:
            internal_ms = int(internal_ms_raw)
        except ValueError:
            internal_ms = 0
        received_at = (
            datetime.fromtimestamp(internal_ms / 1000) if internal_ms else datetime.utcnow()
        )

        labels = list(msg.get("labelIds") or [])
        has_attachments = any(
            bool(p.get("filename")) for p in _walk_parts(payload) if p is not payload
        )

        return Envelope(
            source=self.name,
            source_id=msg.get("id", ""),
            title=subject,
            body=body,
            received_at=received_at,
            labels=labels,
            metadata={
                "thread_id": msg.get("threadId", ""),
                "message_id_header": message_id_hdr,
                "from": from_hdr,
                "to": to_hdr,
                "cc": cc_hdr,
                "in_reply_to": in_reply_to,
                "references": references,
                "snippet": msg.get("snippet", ""),
                "has_attachments": has_attachments,
            },
        )

    # ------------------------------------------------------------------
    # Execute actions
    # ------------------------------------------------------------------

    async def execute_action(self, envelope: Envelope, action: dict[str, Any]) -> None:
        """Execute a user-approved action. Raises if the adaptor isn't started."""
        if self._service is None:
            raise RuntimeError("GmailAdaptor not started")
        action_type = action.get("type", "")
        if action_type == "reply":
            await anyio.to_thread.run_sync(self._send_reply, envelope, action)
        elif action_type == "archive":
            await anyio.to_thread.run_sync(self._modify_labels, envelope, [], ["INBOX"])
        elif action_type == "label":
            add = [str(x) for x in action.get("labels") or []]
            await anyio.to_thread.run_sync(self._modify_labels, envelope, add, [])
        elif action_type == "trash":
            await anyio.to_thread.run_sync(self._trash, envelope)
        else:
            raise ValueError(f"Unknown gmail action type: {action_type!r}")

    def _send_reply(self, envelope: Envelope, action: dict[str, Any]) -> None:
        meta = envelope.metadata
        thread_id = str(meta.get("thread_id", ""))
        msg_id_hdr = str(meta.get("message_id_header", ""))
        references = str(meta.get("references", ""))
        from_hdr = str(meta.get("from", ""))
        to_addr = str(action.get("to") or parseaddr(from_hdr)[1])
        if not to_addr:
            raise ValueError("No reply recipient resolvable from envelope")

        subject = envelope.title or ""
        if subject and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        mime = EmailMessage()
        mime["To"] = to_addr
        mime["Subject"] = subject
        if msg_id_hdr:
            mime["In-Reply-To"] = msg_id_hdr
            mime["References"] = f"{references} {msg_id_hdr}".strip() if references else msg_id_hdr
        mime.set_content(str(action.get("body", "")))

        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
        body: dict[str, Any] = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id
        self._service.users().messages().send(userId=self._user_id, body=body).execute()

    def _modify_labels(self, envelope: Envelope, add: list[str], remove: list[str]) -> None:
        self._service.users().messages().modify(
            userId=self._user_id,
            id=envelope.source_id,
            body={"addLabelIds": add, "removeLabelIds": remove},
        ).execute()

    def _trash(self, envelope: Envelope) -> None:
        self._service.users().messages().trash(
            userId=self._user_id, id=envelope.source_id
        ).execute()

    # ------------------------------------------------------------------
    # Seen-set (caller owns persistence)
    # ------------------------------------------------------------------

    def _record_seen(self, message_id: str) -> None:
        if message_id in self._seen_index:
            return
        if len(self._seen) == SEEN_SET_MAX:
            evicted = self._seen[0]
            self._seen_index.discard(evicted)
        self._seen.append(message_id)
        self._seen_index.add(message_id)

    def export_seen(self) -> list[str]:
        """Return the current seen-message-id deque for external persistence."""
        return list(self._seen)

    def restore_seen(self, entries: list[str]) -> None:
        """Rehydrate the seen-set from a previous run (caller owns the storage)."""
        for mid in entries[-SEEN_SET_MAX:]:
            if isinstance(mid, str):
                self._record_seen(mid)
