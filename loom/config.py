"""Configuration loading and persistence for Loom."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_LOOM_DIR = Path.home() / ".loom"


@dataclass
class DaemonSettings:
    host: str = "127.0.0.1"
    port: int = 8732
    proxy: str | None = None


@dataclass
class AgentSettings:
    max_concurrent: int = 3
    model: str = "sonnet"


@dataclass
class PathSettings:
    policies_dir: Path = field(default_factory=lambda: DEFAULT_LOOM_DIR / "policies")
    prompts_dir: Path = field(default_factory=lambda: DEFAULT_LOOM_DIR / "prompts")
    data_dir: Path = field(default_factory=lambda: DEFAULT_LOOM_DIR / "data")
    credentials_dir: Path = field(default_factory=lambda: DEFAULT_LOOM_DIR / "credentials")


@dataclass
class GroupConfig:
    """Shared policy defaults for a named collection of sources."""

    name: str
    prompt: str = ""
    system_prompt: str = ""
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    model: str = ""
    max_turns: int | None = None
    auto_approve: bool = False


@dataclass
class LoomConfig:
    daemon: DaemonSettings = field(default_factory=DaemonSettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    sources: list[dict[str, Any]] = field(default_factory=list)
    groups: dict[str, GroupConfig] = field(default_factory=dict)
    paths: PathSettings = field(default_factory=PathSettings)


def _expand_paths(data: dict[str, Any]) -> dict[str, Any]:
    """Expand ~ in path values."""
    result = {}
    for k, v in data.items():
        if isinstance(v, str) and v.startswith("~"):
            result[k] = str(Path(v).expanduser())
        else:
            result[k] = v
    return result


def load_config(path: Path | None = None) -> LoomConfig:
    """Load configuration from YAML file.

    Returns a default config if the file does not exist.
    """
    config_path = path or DEFAULT_LOOM_DIR / "config.yaml"
    if not config_path.exists():
        return LoomConfig()

    text = config_path.read_text()
    if not text.strip():
        return LoomConfig()

    raw = yaml.safe_load(text)
    if not raw or not isinstance(raw, dict):
        return LoomConfig()

    daemon_raw = raw.get("daemon", {})
    daemon = DaemonSettings(
        host=daemon_raw.get("host", "127.0.0.1"),
        port=daemon_raw.get("port", 8732),
        proxy=daemon_raw.get("proxy"),
    )
    agent = AgentSettings(**raw.get("agent", {}))

    paths_raw = raw.get("paths", {})
    paths = PathSettings(
        policies_dir=Path(
            paths_raw.get("policies_dir", DEFAULT_LOOM_DIR / "policies")
        ).expanduser(),
        prompts_dir=Path(paths_raw.get("prompts_dir", DEFAULT_LOOM_DIR / "prompts")).expanduser(),
        data_dir=Path(paths_raw.get("data_dir", DEFAULT_LOOM_DIR / "data")).expanduser(),
        credentials_dir=Path(
            paths_raw.get("credentials_dir", DEFAULT_LOOM_DIR / "credentials")
        ).expanduser(),
    )

    sources = []
    for s in raw.get("sources", []):
        if isinstance(s, dict) and "kind" in s:
            sources.append(_expand_paths(s))

    groups = {}
    for name, gcfg in raw.get("groups", {}).items():
        if isinstance(gcfg, dict):
            groups[name] = GroupConfig(name=name, **gcfg)

    return LoomConfig(daemon=daemon, agent=agent, sources=sources, groups=groups, paths=paths)


def save_config(config: LoomConfig, path: Path | None = None) -> None:
    """Save configuration to YAML file."""
    config_path = path or DEFAULT_LOOM_DIR / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    daemon_dict: dict[str, Any] = {
        "host": config.daemon.host,
        "port": config.daemon.port,
    }
    if config.daemon.proxy:
        daemon_dict["proxy"] = config.daemon.proxy
    data: dict[str, Any] = {
        "daemon": daemon_dict,
        "agent": {
            "max_concurrent": config.agent.max_concurrent,
            "model": config.agent.model,
        },
        "sources": config.sources,
    }
    if config.groups:
        data["groups"] = {
            name: {
                k: v
                for k, v in {
                    "prompt": g.prompt,
                    "system_prompt": g.system_prompt,
                    "skills": g.skills,
                    "tools": g.tools,
                    "model": g.model,
                    "max_turns": g.max_turns,
                    "auto_approve": g.auto_approve,
                }.items()
                if v  # omit empty/falsy defaults
            }
            for name, g in config.groups.items()
        }
    data["paths"] = {
        "policies_dir": str(config.paths.policies_dir),
        "prompts_dir": str(config.paths.prompts_dir),
        "data_dir": str(config.paths.data_dir),
        "credentials_dir": str(config.paths.credentials_dir),
    }

    config_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    logger.info("Config saved to %s", config_path)


def ensure_loom_dirs(config: LoomConfig) -> None:
    """Create all required Loom directories."""
    dirs = [
        DEFAULT_LOOM_DIR,
        config.paths.data_dir,
        config.paths.policies_dir,
        config.paths.prompts_dir,
        config.paths.credentials_dir,
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def check_pid_file(pid_path: Path) -> int | None:
    """Check if a process from a PID file is alive.

    Returns PID if the process is alive, None otherwise.
    Cleans up stale PID files automatically.
    """
    if not pid_path.exists():
        return None
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        pid_path.unlink(missing_ok=True)
        return None
    try:
        os.kill(pid, 0)
        return pid
    except ProcessLookupError:
        pid_path.unlink(missing_ok=True)
        return None
    except PermissionError:
        return pid
