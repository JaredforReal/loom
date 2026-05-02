"""Loom API server — HTTP interface for CLI and WebUI clients.

Serves as the single communication channel between the daemon process
and external consumers (CLI commands, web frontend, future integrations).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    ctx = getattr(app.state, "ctx", None)
    if ctx is None:
        raise RuntimeError("Daemon not running")
    return ctx


def _envelope_to_dict(e) -> dict:
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
async def list_envelopes(source: str | None = None, group: str | None = None, limit: int = 50):
    ctx = _ctx()
    envelopes = await ctx.mailbox.list_envelopes(source=source, group=group, limit=limit)
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
        entry.setdefault("mode", "active")
        entry["unread"] = counts.get(kind, 0)
        result.append(entry)
    return result


@app.get("/api/groups")
async def list_groups():
    ctx = _ctx()
    counts = await ctx.mailbox.get_unread_count()
    groups: dict[str, dict[str, Any]] = {}
    for src in ctx.config.sources:
        g = src.get("group")
        if not g:
            continue
        if g not in groups:
            gcfg = ctx.config.groups.get(g)
            groups[g] = {
                "name": g,
                "sources": [],
                "unread": 0,
                **({"prompt": gcfg.prompt, "model": gcfg.model} if gcfg else {}),
            }
        groups[g]["sources"].append({k: v for k, v in src.items() if k != "group"})
        groups[g]["unread"] += counts.get(src.get("kind", ""), 0)
    return list(groups.values())


@app.get("/api/groups/{name}")
async def get_group(name: str, limit: int = 50):
    ctx = _ctx()
    sources = [
        {k: v for k, v in src.items() if k != "group"}
        for src in ctx.config.sources
        if src.get("group") == name
    ]
    if not sources and name not in ctx.config.groups:
        return {"error": "not found"}
    gcfg = ctx.config.groups.get(name)
    envelopes = await ctx.mailbox.list_envelopes(group=name, limit=limit)
    return {
        "name": name,
        "sources": sources,
        "envelopes": [_envelope_to_dict(e) for e in envelopes],
        **(
            {
                "prompt": gcfg.prompt,
                "system_prompt": gcfg.system_prompt,
                "model": gcfg.model,
                "skills": gcfg.skills,
                "tools": gcfg.tools,
                "max_turns": gcfg.max_turns,
                "auto_approve": gcfg.auto_approve,
            }
            if gcfg
            else {}
        ),
    }


VALID_MODES = {"active", "fetch-only", "paused"}


@app.patch("/api/sources/{kind}/mode")
async def set_source_mode(kind: str, request: Request):
    ctx = _ctx()
    body = await request.json()
    mode = body.get("mode", "")
    if mode not in VALID_MODES:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=400,
            content={"error": f"invalid mode: {mode!r}"},
        )

    updated = 0
    for src in ctx.config.sources:
        if src.get("kind") == kind:
            src["mode"] = mode
            updated += 1

    if updated == 0:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"error": "source kind not found"})

    from loom.config import save_config

    save_config(ctx.config)

    return {"ok": True, "kind": kind, "mode": mode, "updated": updated}


# --- Settings: Policies ---


def _is_safe_policy_name(name: str) -> bool:
    if "/" in name or "\\" in name or ".." in name:
        return False
    return name.endswith(".yaml") or name.endswith(".yml")


@app.get("/api/settings/policies")
async def get_policies():
    """List all policies — both user-editable and bundled (read-only)."""
    ctx = _ctx()
    user_dir = ctx.config.paths.policies_dir
    bundled_dir = ctx.policy_engine.bundled_dir
    result: list[dict[str, Any]] = []
    if user_dir.exists():
        for p in sorted(user_dir.glob("*.yaml")):
            result.append({"name": p.name, "source": "user", "content": p.read_text()})
    if bundled_dir and bundled_dir.exists():
        for p in sorted(bundled_dir.glob("*.yaml")):
            result.append({"name": p.name, "source": "bundled", "content": p.read_text()})
    return result


@app.get("/api/settings/policies/schema")
async def get_policy_schema():
    """Return field metadata for the form-mode editor."""
    from pathlib import Path

    import loom

    ctx = _ctx()
    user_prompts_dir = ctx.config.paths.prompts_dir
    bundled_prompts_dir = Path(loom.__file__).parent / "prompts"

    prompts: list[str] = []
    seen: set[str] = set()
    for d in (user_prompts_dir, bundled_prompts_dir):
        if d.exists():
            for p in sorted(d.glob("*.md")):
                if p.stem not in seen:
                    seen.add(p.stem)
                    prompts.append(p.stem)

    return {
        "sources": ["github", "gmail", "rss", "arxiv"],
        "models": ["sonnet", "opus", "haiku", ""],
        "tools": ["Read", "Grep", "Glob", "Bash", "WebFetch", "WebSearch", "Edit", "Write"],
        "prompts": prompts,
        "groups": list(ctx.config.groups.keys()),
        "match_fields": ["source", "group", "labels", "source_id_pattern", "title_pattern"],
        "action_fields": [
            "priority",
            "agent",
            "prompt",
            "auto_approve",
            "batch",
            "batch_window",
            "tools",
            "max_turns",
            "system_prompt",
            "model",
            "skills",
            "cwd",
        ],
    }


@app.get("/api/settings/policies/{name}")
async def get_policy(name: str):
    """Return the content of a single policy file (user or bundled)."""
    if not _is_safe_policy_name(name):
        return JSONResponse(status_code=400, content={"error": "invalid policy name"})
    ctx = _ctx()
    user_path = ctx.config.paths.policies_dir / name
    if user_path.exists():
        return {"name": name, "source": "user", "content": user_path.read_text()}
    bundled_dir = ctx.policy_engine.bundled_dir
    if bundled_dir:
        bundled_path = bundled_dir / name
        if bundled_path.exists():
            return {"name": name, "source": "bundled", "content": bundled_path.read_text()}
    return JSONResponse(status_code=404, content={"error": "not found"})


@app.put("/api/settings/policies/{name}")
async def save_policy(name: str, request: Request):
    """Save a user policy and hot-reload the engine."""
    if not _is_safe_policy_name(name):
        return JSONResponse(status_code=400, content={"error": "invalid policy name"})
    ctx = _ctx()
    body = await request.json()
    content = body.get("content", "")
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return JSONResponse(status_code=400, content={"error": f"invalid YAML: {exc}"})
    if data is not None and not isinstance(data, dict):
        return JSONResponse(
            status_code=400,
            content={"error": "policy must be a YAML object with 'rules:' key"},
        )

    path = ctx.config.paths.policies_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    ctx.policy_engine.reload()
    return {"saved": name, "rules": len(ctx.policy_engine.list_rules())}


@app.delete("/api/settings/policies/{name}")
async def delete_policy(name: str):
    """Delete a user policy and hot-reload the engine. Bundled policies cannot be deleted."""
    if not _is_safe_policy_name(name):
        return JSONResponse(status_code=400, content={"error": "invalid policy name"})
    ctx = _ctx()
    path = ctx.config.paths.policies_dir / name
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "not found"})
    path.unlink()
    ctx.policy_engine.reload()
    return {"deleted": name, "rules": len(ctx.policy_engine.list_rules())}


@app.post("/api/settings/policies/reload")
async def reload_policies():
    """Manually trigger a reload (useful for debugging)."""
    ctx = _ctx()
    ctx.policy_engine.reload()
    return {"rules": len(ctx.policy_engine.list_rules())}


@app.get("/api/settings/prompts")
async def get_prompts():
    """List all prompts — both user-editable and bundled (read-only)."""
    ctx = _ctx()
    user_dir = ctx.config.paths.prompts_dir
    bundled_dir = ctx.session_mgr.bundled_prompt_dir
    result: list[dict[str, Any]] = []
    if user_dir.exists():
        for p in sorted(user_dir.glob("*.md")):
            result.append({"name": p.name, "source": "user", "content": p.read_text()})
    if bundled_dir and bundled_dir.exists():
        for p in sorted(bundled_dir.glob("*.md")):
            result.append({"name": p.name, "source": "bundled", "content": p.read_text()})
    return result


def _is_safe_prompt_name(name: str) -> bool:
    if "/" in name or "\\" in name or ".." in name:
        return False
    return name.endswith(".md")


@app.get("/api/settings/prompts/{name}")
async def get_prompt(name: str):
    """Return the content of a single prompt file (user or bundled)."""
    if not _is_safe_prompt_name(name):
        return JSONResponse(status_code=400, content={"error": "invalid prompt name"})
    ctx = _ctx()
    user_path = ctx.config.paths.prompts_dir / name
    if user_path.exists():
        return {"name": name, "source": "user", "content": user_path.read_text()}
    bundled_dir = ctx.session_mgr.bundled_prompt_dir
    if bundled_dir:
        bundled_path = bundled_dir / name
        if bundled_path.exists():
            return {"name": name, "source": "bundled", "content": bundled_path.read_text()}
    return JSONResponse(status_code=404, content={"error": "not found"})


@app.put("/api/settings/prompts/{name}")
async def save_prompt(name: str, request: Request):
    """Save a user prompt and hot-reload the session manager's templates."""
    if not _is_safe_prompt_name(name):
        return JSONResponse(status_code=400, content={"error": "invalid prompt name"})
    ctx = _ctx()
    body = await request.json()
    content = body.get("content", "")
    if not isinstance(content, str):
        return JSONResponse(status_code=400, content={"error": "content must be a string"})

    path = ctx.config.paths.prompts_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    ctx.session_mgr.reload_prompts()
    return {"saved": name, "templates": len(ctx.session_mgr.list_template_names())}


@app.delete("/api/settings/prompts/{name}")
async def delete_prompt(name: str):
    """Delete a user prompt and hot-reload. Bundled prompts cannot be deleted."""
    if not _is_safe_prompt_name(name):
        return JSONResponse(status_code=400, content={"error": "invalid prompt name"})
    ctx = _ctx()
    path = ctx.config.paths.prompts_dir / name
    if not path.exists():
        return JSONResponse(status_code=404, content={"error": "not found"})
    path.unlink()
    ctx.session_mgr.reload_prompts()
    return {"deleted": name, "templates": len(ctx.session_mgr.list_template_names())}


@app.post("/api/settings/prompts/reload")
async def reload_prompts():
    """Manually trigger a reload of prompt templates."""
    ctx = _ctx()
    ctx.session_mgr.reload_prompts()
    return {"templates": len(ctx.session_mgr.list_template_names())}


# --- Agent / Mailbox control ---


@app.get("/api/agent")
async def get_agent_status():
    ctx = _ctx()
    return {
        "enabled": ctx.dispatcher.agent_enabled,
        "active_sessions": ctx.session_mgr.active_count,
        "max_concurrent": ctx.session_mgr._max_concurrent,
    }


@app.post("/api/agent/on")
async def agent_on():
    ctx = _ctx()
    ctx.dispatcher.set_agent_enabled(True)
    return {"enabled": True}


@app.post("/api/agent/off")
async def agent_off():
    ctx = _ctx()
    ctx.dispatcher.set_agent_enabled(False)
    return {"enabled": False}


@app.get("/api/mailbox")
async def get_mailbox_status():
    ctx = _ctx()
    running = [ad.name for ad in ctx.adaptors if ad.is_running]
    return {
        "enabled": ctx.mailbox_enabled,
        "adaptors_running": len(running),
        "adaptors_total": len(ctx.adaptors),
        "adaptor_names": running,
    }


@app.post("/api/mailbox/on")
async def mailbox_on():
    ctx = _ctx()
    await ctx.set_mailbox_enabled(True)
    return {"enabled": True}


@app.post("/api/mailbox/off")
async def mailbox_off():
    ctx = _ctx()
    await ctx.set_mailbox_enabled(False)
    return {"enabled": False}
