"""Unit tests for repository slug utility."""

from __future__ import annotations

import pytest

from ghillie.common.slug import parse_repo_slug, repo_slug


def test_repo_slug_combines_owner_and_name() -> None:
    """repo_slug returns owner/name format."""
    assert repo_slug("leynos", "ghillie") == "leynos/ghillie"
    assert repo_slug("org", "repo") == "org/repo"


def test_parse_repo_slug_splits_owner_and_name() -> None:
    """parse_repo_slug returns (owner, name) for valid slugs."""
    assert parse_repo_slug("leynos/ghillie") == ("leynos", "ghillie")
    assert parse_repo_slug("Owner-Org/Repo_Name") == ("Owner-Org", "Repo_Name")


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "   ",
        "/",
        "invalid",
        "owner/name/extra",
        r"owner\\name",
        "owner/",
        "/name",
        "owner//name",
    ],
)
def test_parse_repo_slug_rejects_invalid_slugs(slug: str) -> None:
    """parse_repo_slug raises ValueError for invalid slugs."""
    with pytest.raises(ValueError, match="Invalid repository slug"):
        parse_repo_slug(slug)
