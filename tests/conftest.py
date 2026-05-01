"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_loom_dir(tmp_path: Path) -> Path:
    """Provide a temporary ~/.loom directory with all subdirectories."""
    loom_dir = tmp_path / ".loom"
    loom_dir.mkdir()
    (loom_dir / "data").mkdir()
    (loom_dir / "policies").mkdir()
    (loom_dir / "prompts").mkdir()
    (loom_dir / "credentials").mkdir()
    return loom_dir


@pytest.fixture
def db_path(tmp_loom_dir: Path) -> Path:
    """Provide a temp database path."""
    return tmp_loom_dir / "data" / "test.db"
