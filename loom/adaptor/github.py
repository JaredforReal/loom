"""GitHub adaptor — webhooks, issues, PRs."""

from __future__ import annotations

from typing import Any

from loom.adaptor.base import BaseAdaptor
from loom.core.envelope import Envelope


class GitHubAdaptor(BaseAdaptor):
    """Subscribes to GitHub repo events via webhooks."""

    name = "github"

    async def start(self) -> None:
        # TODO: Start webhook listener or register webhook
        pass

    async def stop(self) -> None:
        pass

    async def normalize(self, raw_event: Any) -> Envelope:
        # TODO: Parse GitHub webhook payload → Envelope
        return Envelope(source=self.name)

    async def execute_action(self, envelope: Envelope, action: dict) -> None:
        # TODO: Post comment, close issue, merge PR, etc.
        pass
