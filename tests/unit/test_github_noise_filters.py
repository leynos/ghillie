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


@pytest.mark.parametrize(
    ("project_filters", "event_spec", "expected_drop"),
    [
        pytest.param(
            [
                NoiseFilters(ignore_authors=["dependabot[bot]"]),
                NoiseFilters(ignore_labels=["chore/deps"]),
            ],
            EventSpec(
                event_type="github.pull_request",
                source_event_id="21",
                payload={"author_login": "human", "labels": ["chore/deps"]},
            ),
            True,
            id="merges_multiple_projects",
        ),
        pytest.param(
            [
                NoiseFilters(ignore_authors=["dependabot[bot]"]),
                NoiseFilters(ignore_labels=["chore/deps"]),
            ],
            EventSpec(
                event_type="github.pull_request",
                source_event_id="21b",
                payload={"author_login": "dependabot[bot]", "labels": ["ci"]},
            ),
            True,
            id="merges_multiple_projects_authors",
        ),
        pytest.param(
            [
                NoiseFilters(ignore_title_prefixes=["chore:"]),
                NoiseFilters(ignore_paths=["docs/generated/**"]),
            ],
            EventSpec(
                event_type="github.issue",
                source_event_id="21c",
                payload={"title": "chore: bump deps"},
            ),
            True,
            id="merges_multiple_projects_title_prefixes",
        ),
        pytest.param(
            [
                NoiseFilters(ignore_title_prefixes=["chore:"]),
                NoiseFilters(ignore_paths=["docs/generated/**"]),
            ],
            EventSpec(
                event_type="github.doc_change",
                source_event_id="21d",
                payload={"path": "docs/generated/index.md"},
            ),
            True,
            id="merges_multiple_projects_paths",
        ),
        pytest.param(
            [
                NoiseFilters(
                    enabled=False,
                    ignore_authors=["dependabot[bot]"],
                    ignore_labels=["chore/deps"],
                    ignore_paths=["docs/generated/**"],
                    ignore_title_prefixes=["chore:"],
                ),
                NoiseFilters(ignore_authors=[]),
            ],
            EventSpec(
                event_type="github.pull_request",
                source_event_id="22",
                payload={
                    "author_login": "dependabot[bot]",
                    "labels": ["chore/deps"],
                    "path": "docs/generated/index.md",
                    "title": "chore: bump deps",
                },
            ),
            False,
            id="ignores_disabled_project_filters",
        ),
        pytest.param(
            [
                NoiseFilters(
                    toggles=NoiseFilterToggles(
                        ignore_labels=False,
                        ignore_paths=False,
                        ignore_title_prefixes=False,
                    ),
                    ignore_labels=["chore/deps"],
                    ignore_paths=["docs/generated/**"],
                    ignore_title_prefixes=["chore:"],
                )
            ],
            EventSpec(
                event_type="github.pull_request",
                source_event_id="23",
                payload={
                    "author_login": "human",
                    "labels": ["chore/deps"],
                    "path": "docs/generated/index.md",
                    "title": "chore: bump deps",
                },
            ),
            False,
            id="respects_per_dimension_toggles",
        ),
        pytest.param(
            [
                NoiseFilters(
                    ignore_authors=[
                        "Dependabot[bot]",
                        " dependabot[bot]  ",
                        "DEPENDABOT[BOT]",
                    ],
                    ignore_labels=[
                        "Dependencies",
                        "dependencies",
                        " dependencies ",
                    ],
                    ignore_paths=[
                        "docs/",
                        "docs",
                    ],
                    ignore_title_prefixes=[
                        "Chore:",
                        "chore:",
                        "  chore:  ",
                    ],
                )
            ],
            EventSpec(
                event_type="github.doc_change",
                source_event_id="24",
                payload={
                    "author_login": "DEPENDABOT[BOT] ",
                    "labels": [" dependencies", "DEpendencies"],
                    "path": "docs/README.md",
                    "title": "  Chore: normalise and dedupe  ",
                },
            ),
            True,
            id="normalises_and_deduplicates_config_values",
        ),
    ],
)
def test_compile_noise_filters_behavior(
    project_filters: list[NoiseFilters],
    event_spec: EventSpec,
    *,
    expected_drop: bool,
) -> None:
    """compile_noise_filters merges enabled project filters and respects toggles."""
    compiled = compile_noise_filters(project_filters)
    event = GitHubIngestedEvent(
        event_type=event_spec.event_type,
        source_event_id=event_spec.source_event_id,
        occurred_at=dt.datetime.now(dt.UTC),
        payload=dict(event_spec.payload),
    )
    assert compiled.should_drop(event) is expected_drop


def test_compile_noise_filters_deduplicates_paths_and_prefixes() -> None:
    """Tuple-backed filters are de-duped whilst preserving configured order."""
    compiled = compile_noise_filters(
        [
            NoiseFilters(
                ignore_paths=["docs/", "docs", "src/**", "docs"],
                ignore_title_prefixes=["chore:", "Chore:", "fix:", "fix:"],
            )
        ]
    )
    assert compiled.ignore_paths == ("docs", "src/**")
    assert compiled.ignore_title_prefixes == ("chore:", "fix:")
