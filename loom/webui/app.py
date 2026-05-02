"""Loom WebUI — re-exports the shared FastAPI app from api_server.

WebUI-specific views and frontend logic will be added here in the future.
"""

from loom.api_server import app  # noqa: F401
