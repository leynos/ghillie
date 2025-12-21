"""Unit tests for GitHub ingestion noise filters."""
# ruff: noqa: D103

from __future__ import annotations

import datetime as dt

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


def test_ignore_authors_drops_matching_author_login() -> None:
    event = GitHubIngestedEvent(
        event_type="github.pull_request",
        source_event_id="17",
        occurred_at=dt.datetime.now(dt.UTC),
        payload={"author_login": "dependabot[bot]"},
    )
    _assert_noise_filter_drops_event(
        noise_filters=NoiseFilters(ignore_authors=["dependabot[bot]"]),
        event=event,
        expected_drop=True,
    )


def test_ignore_authors_can_be_disabled_per_project() -> None:
    event = GitHubIngestedEvent(
        event_type="github.pull_request",
        source_event_id="17",
        occurred_at=dt.datetime.now(dt.UTC),
        payload={"author_login": "dependabot[bot]"},
    )
    _assert_noise_filter_drops_event(
        noise_filters=NoiseFilters(
            toggles=NoiseFilterToggles(ignore_authors=False),
            ignore_authors=["dependabot[bot]"],
        ),
        event=event,
        expected_drop=False,
    )


def test_ignore_title_prefixes_drops_case_insensitive_prefix_match() -> None:
    event = GitHubIngestedEvent(
        event_type="github.issue",
        source_event_id="101",
        occurred_at=dt.datetime.now(dt.UTC),
        payload={"title": "Chore: bump dependencies"},
    )
    _assert_noise_filter_drops_event(
        noise_filters=NoiseFilters(ignore_title_prefixes=["chore:"]),
        event=event,
        expected_drop=True,
    )


def test_ignore_labels_drops_matching_label() -> None:
    event = GitHubIngestedEvent(
        event_type="github.pull_request",
        source_event_id="17",
        occurred_at=dt.datetime.now(dt.UTC),
        payload={"labels": ["chore/deps", "ci"]},
    )
    _assert_noise_filter_drops_event(
        noise_filters=NoiseFilters(ignore_labels=["chore/deps"]),
        event=event,
        expected_drop=True,
    )


def test_ignore_paths_drops_matching_doc_change_path_glob() -> None:
    event = GitHubIngestedEvent(
        event_type="github.doc_change",
        source_event_id="abc123:docs/generated/index.md",
        occurred_at=dt.datetime.now(dt.UTC),
        payload={"path": "docs/generated/index.md"},
    )
    _assert_noise_filter_drops_event(
        noise_filters=NoiseFilters(ignore_paths=["docs/generated/**"]),
        event=event,
        expected_drop=True,
    )
