"""Tests for loom.config module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from loom.config import (
    DEFAULT_LOOM_DIR,
    DaemonSettings,
    LoomConfig,
    PathSettings,
    ensure_loom_dirs,
    load_config,
    save_config,
)


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        config = load_config(tmp_path / "nonexistent.yaml")
        assert config.daemon.host == "127.0.0.1"
        assert config.daemon.port == 8732
        assert config.agent.max_concurrent == 3
        assert config.sources == []

    def test_empty_file_returns_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "config.yaml"
        p.write_text("")
        config = load_config(p)
        assert config.sources == []

    def test_loads_full_config(self, tmp_path: Path) -> None:
        p = tmp_path / "config.yaml"
        data = {
            "daemon": {"host": "0.0.0.0", "port": 9999},
            "agent": {"max_concurrent": 5, "model": "opus"},
            "sources": [
                {"kind": "github", "owner": "acme", "repo": "app"},
                {"kind": "gmail", "client_secrets": "/path/to/secret.json"},
            ],
            "paths": {
                "policies_dir": str(tmp_path / "policies"),
                "data_dir": str(tmp_path / "data"),
            },
        }
        p.write_text(yaml.dump(data))
        config = load_config(p)

        assert config.daemon.host == "0.0.0.0"
        assert config.daemon.port == 9999
        assert config.agent.max_concurrent == 5
        assert config.agent.model == "opus"
        assert len(config.sources) == 2
        assert config.sources[0]["kind"] == "github"
        assert config.sources[0]["owner"] == "acme"
        assert config.paths.policies_dir == tmp_path / "policies"
        assert config.paths.data_dir == tmp_path / "data"

    def test_expands_tilde_in_paths(self, tmp_path: Path) -> None:
        p = tmp_path / "config.yaml"
        data = {
            "paths": {
                "data_dir": "~/custom-data",
            },
        }
        p.write_text(yaml.dump(data))
        config = load_config(p)
        assert str(config.paths.data_dir).startswith(str(Path.home()))
        assert "~" not in str(config.paths.data_dir)

    def test_expands_tilde_in_sources(self, tmp_path: Path) -> None:
        p = tmp_path / "config.yaml"
        data = {
            "sources": [
                {"kind": "gmail", "client_secrets": "~/creds/secret.json"},
            ],
        }
        p.write_text(yaml.dump(data))
        config = load_config(p)
        assert "~" not in config.sources[0]["client_secrets"]

    def test_skips_source_without_kind(self, tmp_path: Path) -> None:
        p = tmp_path / "config.yaml"
        data = {
            "sources": [
                {"owner": "acme", "repo": "app"},
                {"kind": "github", "owner": "acme", "repo": "lib"},
            ],
        }
        p.write_text(yaml.dump(data))
        config = load_config(p)
        assert len(config.sources) == 1
        assert config.sources[0]["repo"] == "lib"


class TestSaveConfig:
    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        p = tmp_path / "config.yaml"
        config = LoomConfig(
            daemon=DaemonSettings(host="0.0.0.0", port=9999),
            sources=[{"kind": "github", "owner": "acme", "repo": "app"}],
        )
        save_config(config, path=p)

        loaded = load_config(p)
        assert loaded.daemon.host == "0.0.0.0"
        assert loaded.daemon.port == 9999
        assert len(loaded.sources) == 1
        assert loaded.sources[0]["owner"] == "acme"

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        p = tmp_path / "deep" / "nested" / "config.yaml"
        config = LoomConfig()
        save_config(config, path=p)
        assert p.exists()

    def test_file_is_valid_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "config.yaml"
        save_config(LoomConfig(), path=p)
        data = yaml.safe_load(p.read_text())
        assert "daemon" in data
        assert "sources" in data


class TestEnsureLoomDirs:
    def test_creates_all_directories(self, tmp_path: Path) -> None:
        config = LoomConfig(
            paths=PathSettings(
                data_dir=tmp_path / "data",
                policies_dir=tmp_path / "policies",
                prompts_dir=tmp_path / "prompts",
                credentials_dir=tmp_path / "credentials",
            ),
        )
        ensure_loom_dirs(config)
        assert (tmp_path / "data").is_dir()
        assert (tmp_path / "policies").is_dir()
        assert (tmp_path / "prompts").is_dir()
        assert (tmp_path / "credentials").is_dir()

    def test_idempotent(self, tmp_path: Path) -> None:
        config = LoomConfig(
            paths=PathSettings(data_dir=tmp_path / "data"),
        )
        ensure_loom_dirs(config)
        ensure_loom_dirs(config)  # no error
        assert (tmp_path / "data").is_dir()
