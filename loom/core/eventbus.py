"""In-process async event bus for decoupled communication."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Coroutine


Callback = Callable[[str, Any], Coroutine[Any, Any, None]]


class EventBus:
    """Simple async pub/sub event bus.

    Usage:
        bus = EventBus()
        bus.subscribe("new_envelope", my_handler)
        await bus.publish("new_envelope", envelope)
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callback]] = defaultdict(list)

    def subscribe(self, event: str, callback: Callback) -> None:
        self._subscribers[event].append(callback)

    def unsubscribe(self, event: str, callback: Callback) -> None:
        self._subscribers[event].remove(callback)

    async def publish(self, event: str, data: Any = None) -> None:
        for callback in self._subscribers.get(event, []):
            asyncio.create_task(callback(event, data))
