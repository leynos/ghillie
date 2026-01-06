"""Pytest fixtures for Helm chart testing."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


def _find_repo_root(start: Path) -> Path:
    """Locate the repository root by finding pyproject.toml."""
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    msg = f"Failed to locate repository root from: {start}"
    raise FileNotFoundError(msg)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Return the repository root path."""
    return _find_repo_root(Path(__file__).resolve())


@pytest.fixture(scope="session")
def chart_path(repo_root: Path) -> Path:
    """Return the path to the Ghillie Helm chart."""
    return repo_root / "charts" / "ghillie"


@pytest.fixture(scope="session")
def fixtures_path(repo_root: Path) -> Path:
    """Return the path to test fixtures."""
    return repo_root / "tests" / "helm" / "fixtures"


@pytest.fixture(scope="session")
def require_helm() -> None:
    """Skip tests if helm is not installed."""
    if shutil.which("helm") is None:
        pytest.skip("helm is not installed")
