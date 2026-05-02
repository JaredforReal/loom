"""Loom WebUI — serves the API and built frontend static files.

In development, the Vite dev server proxies /api to the daemon.
In production, this module mounts the built frontend from webui/dist/.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.staticfiles import StaticFiles

from loom.api_server import app  # noqa: F401 — re-exported for uvicorn

_DIST = Path(__file__).parent / "dist"


def _mount_spa() -> None:
    """Mount the built frontend as a catch-all SPA when dist/ exists."""
    if _DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="spa")


_mount_spa()
