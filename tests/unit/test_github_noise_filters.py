"""Unit tests for GitHub ingestion noise filters."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass  # noqa: ICN003

import pytest

from ghillie.catalogue.models import NoiseFilters, NoiseFilterToggles
from ghillie.github.models import GitHubIngestedEvent
from ghillie.github.noise import compile_noise_filters


@dataclass(frozen=True)
class EventSpec:
    """Specification for constructing a test GitHub event."""

    event_type: str
    source_event_id: str
    payload: dict[str, object]


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
    ("noise_filters", "event_spec", "expected_drop"),
    [
        pytest.param(
            NoiseFilters(ignore_authors=["dependabot[bot]"]),
            EventSpec(
                event_type="github.pull_request",
                source_event_id="17",
                payload={"author_login": "dependabot[bot]"},
            ),
            True,
            id="ignore_authors_drops_matching_author_login",
        ),
        pytest.param(
            NoiseFilters(
                toggles=NoiseFilterToggles(ignore_authors=False),
                ignore_authors=["dependabot[bot]"],
            ),
            EventSpec(
                event_type="github.pull_request",
                source_event_id="17",
                payload={"author_login": "dependabot[bot]"},
            ),
            False,
            id="ignore_authors_can_be_disabled_per_project",
        ),
        pytest.param(
            NoiseFilters(ignore_title_prefixes=["chore:"]),
            EventSpec(
                event_type="github.issue",
                source_event_id="101",
                payload={"title": "Chore: bump dependencies"},
            ),
            True,
            id="ignore_title_prefixes_drops_case_insensitive_prefix_match",
        ),
        pytest.param(
            NoiseFilters(ignore_labels=["chore/deps"]),
            EventSpec(
                event_type="github.pull_request",
                source_event_id="17",
                payload={"labels": ["chore/deps", "ci"]},
            ),
            True,
            id="ignore_labels_drops_matching_label",
        ),
        pytest.param(
            NoiseFilters(ignore_paths=["docs/generated/**"]),
            EventSpec(
                event_type="github.doc_change",
                source_event_id="abc123:docs/generated/index.md",
                payload={"path": "docs/generated/index.md"},
            ),
            True,
            id="ignore_paths_drops_matching_doc_change_path_glob",
        ),
    ],
)
def test_noise_filter_behavior(
    noise_filters: NoiseFilters,
    event_spec: EventSpec,
    *,
    expected_drop: bool,
) -> None:
    """Verify noise filters drop or retain events based on configuration."""
    event = GitHubIngestedEvent(
        event_type=event_spec.event_type,
        source_event_id=event_spec.source_event_id,
        occurred_at=dt.datetime.now(dt.UTC),
        payload=dict(event_spec.payload),
    )
    _assert_noise_filter_drops_event(
        noise_filters=noise_filters,
        event=event,
        expected_drop=expected_drop,
    )
