"""Unit tests for repository slug utility."""

from __future__ import annotations

from ghillie.common.slug import repo_slug


def test_repo_slug_combines_owner_and_name() -> None:
    """repo_slug returns owner/name format."""
    assert repo_slug("leynos", "ghillie") == "leynos/ghillie"
    assert repo_slug("org", "repo") == "org/repo"
