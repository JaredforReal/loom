"""FastAPI application for the Loom web UI."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from loom.core.envelope import EnvelopeStatus

app = FastAPI(title="Loom", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _ctx():
    from loom.daemon import get_context

    return get_context()


def _envelope_to_dict(e) -> dict:
    """Convert Envelope dataclass to JSON-serializable dict."""
    d = asdict(e)
    d["received_at"] = e.received_at.isoformat() if e.received_at else None
    d["status"] = str(e.status)
    return d


# --- Status ---


@app.get("/api/status")
async def get_status():
    ctx = _ctx()
    s = ctx.metrics.snapshot()
    return {
        "online": s.online,
        "active_sessions": s.active_sessions,
        "queue_backlog": s.queue_backlog,
    }


# --- Envelopes / Feed ---


@app.get("/api/envelopes")
async def list_envelopes(source: str | None = None, limit: int = 50):
    ctx = _ctx()
    envelopes = await ctx.mailbox.list_envelopes(source=source, limit=limit)
    return [_envelope_to_dict(e) for e in envelopes]


@app.get("/api/envelopes/{envelope_id}")
async def get_envelope(envelope_id: str):
    ctx = _ctx()
    envelope = await ctx.store.get_envelope(envelope_id)
    if envelope is None:
        return {"error": "not found"}
    return _envelope_to_dict(envelope)


@app.post("/api/envelopes/{envelope_id}/approve")
async def approve_envelope(envelope_id: str):
    ctx = _ctx()
    envelope = await ctx.mailbox.update_status(envelope_id, EnvelopeStatus.DONE)
    if envelope is None:
        return {"error": "not found"}
    return {"status": "approved", "id": envelope.id}


@app.post("/api/envelopes/{envelope_id}/dismiss")
async def dismiss_envelope(envelope_id: str):
    ctx = _ctx()
    envelope = await ctx.mailbox.update_status(envelope_id, EnvelopeStatus.DISMISSED)
    if envelope is None:
        return {"error": "not found"}
    return {"status": "dismissed", "id": envelope.id}


# --- Sources ---


@app.get("/api/sources")
async def list_sources():
    ctx = _ctx()
    counts = await ctx.mailbox.get_unread_count()
    result = []
    for src in ctx.config.sources:
        kind = src.get("kind", "unknown")
        entry = dict(src)
        entry["unread"] = counts.get(kind, 0)
        result.append(entry)
    return result


# --- Settings ---


@app.get("/api/settings/policies")
async def get_policies():
    ctx = _ctx()
    policy_dir = ctx.config.paths.policies_dir
    if not policy_dir.exists():
        return []
    return [{"name": p.name, "path": str(p)} for p in sorted(policy_dir.glob("*.yaml"))]


@app.put("/api/settings/policies/{name}")
async def save_policy(name: str, content: str):
    ctx = _ctx()
    path = ctx.config.paths.policies_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return {"saved": name}


@app.get("/api/settings/prompts")
async def get_prompts():
    ctx = _ctx()
    prompt_dir = ctx.config.paths.prompts_dir
    if not prompt_dir.exists():
        return []
    return [{"name": p.stem, "path": str(p)} for p in sorted(prompt_dir.glob("*.md"))]
