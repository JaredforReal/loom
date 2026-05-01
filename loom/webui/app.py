"""FastAPI application for the Loom web UI."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Loom", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Status ---


@app.get("/api/status")
async def get_status():
    """Daemon status bar data."""
    return {"online": False, "active_sessions": 0, "queue_backlog": 0}


# --- Envelopes / Feed ---


@app.get("/api/envelopes")
async def list_envelopes(source: str | None = None, limit: int = 50):
    """List envelopes for the feed view."""
    return []


@app.get("/api/envelopes/{envelope_id}")
async def get_envelope(envelope_id: str):
    """Get a single envelope with full detail."""
    return None


@app.post("/api/envelopes/{envelope_id}/approve")
async def approve_envelope(envelope_id: str):
    """User approves the proposed action."""
    pass


@app.post("/api/envelopes/{envelope_id}/dismiss")
async def dismiss_envelope(envelope_id: str):
    """User dismisses the envelope."""
    pass


# --- Sources ---


@app.get("/api/sources")
async def list_sources():
    """List configured sources with unread counts."""
    return []


# --- Settings ---


@app.get("/api/settings/policies")
async def get_policies():
    """List policy rule files."""
    return []


@app.put("/api/settings/policies/{name}")
async def save_policy(name: str, content: str):
    """Save a policy file."""
    pass


@app.get("/api/settings/prompts")
async def get_prompts():
    """List prompt templates."""
    return []
