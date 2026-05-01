"""Daemon status, queue depth, and session metrics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DaemonStatus:
    """Snapshot of the daemon's current state."""

    online: bool = False
    active_sessions: int = 0
    queue_backlog: int = 0
    uptime_seconds: int = 0


class MetricsCollector:
    """Collects runtime metrics for the status bar and API."""

    def __init__(self) -> None:
        self._status = DaemonStatus()

    def set_online(self, online: bool) -> None:
        self._status.online = online

    def update(self, active_sessions: int, queue_backlog: int) -> None:
        self._status.active_sessions = active_sessions
        self._status.queue_backlog = queue_backlog

    def snapshot(self) -> DaemonStatus:
        return self._status
