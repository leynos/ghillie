"""Unit tests for GitHub ingestion noise filters."""

from __future__ import annotations

import datetime as dt

import pytest

from ghillie.catalogue.models import NoiseFilters, NoiseFilterToggles
from ghillie.github.models import GitHubIngestedEvent
from ghillie.github.noise import compile_noise_filters


def _assert_noise_filter_drops_event(
    noise_filters: NoiseFilters,
    event: GitHubIngestedEvent,
    *,
    expected_drop: bool,
) -> None:
    """Assert that compiled noise filters drop (or retain) an event as expected."""
    compiled = compile_noise_filters([noise_filters])
    assert compiled.should_drop(event) is expected_drop


@pytest.mark.parametrize(
    ("noise_filters", "event_type", "source_event_id", "payload", "expected_drop"),
    [
        pytest.param(
            NoiseFilters(ignore_authors=["dependabot[bot]"]),
            "github.pull_request",
            "17",
            {"author_login": "dependabot[bot]"},
            True,
            id="ignore_authors_drops_matching_author_login",
        ),
        pytest.param(
            NoiseFilters(
                toggles=NoiseFilterToggles(ignore_authors=False),
                ignore_authors=["dependabot[bot]"],
            ),
            "github.pull_request",
            "17",
            {"author_login": "dependabot[bot]"},
            False,
            id="ignore_authors_can_be_disabled_per_project",
        ),
        pytest.param(
            NoiseFilters(ignore_title_prefixes=["chore:"]),
            "github.issue",
            "101",
            {"title": "Chore: bump dependencies"},
            True,
            id="ignore_title_prefixes_drops_case_insensitive_prefix_match",
        ),
        pytest.param(
            NoiseFilters(ignore_labels=["chore/deps"]),
            "github.pull_request",
            "17",
            {"labels": ["chore/deps", "ci"]},
            True,
            id="ignore_labels_drops_matching_label",
        ),
        pytest.param(
            NoiseFilters(ignore_paths=["docs/generated/**"]),
            "github.doc_change",
            "abc123:docs/generated/index.md",
            {"path": "docs/generated/index.md"},
            True,
            id="ignore_paths_drops_matching_doc_change_path_glob",
        ),
    ],
)
def test_noise_filter_behavior(  # noqa: PLR0913
    noise_filters: NoiseFilters,
    event_type: str,
    source_event_id: str,
    payload: dict[str, object],
    *,
    expected_drop: bool,
) -> None:
    """Verify noise filters drop or retain events based on configuration."""
    event = GitHubIngestedEvent(
        event_type=event_type,
        source_event_id=source_event_id,
        occurred_at=dt.datetime.now(dt.UTC),
        payload=dict(payload),
    )
    _assert_noise_filter_drops_event(
        noise_filters=noise_filters,
        event=event,
        expected_drop=expected_drop,
    )
