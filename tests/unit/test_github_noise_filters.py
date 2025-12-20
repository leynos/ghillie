"""Unit tests for GitHub ingestion noise filters."""
# ruff: noqa: D103

from __future__ import annotations

import datetime as dt

from ghillie.catalogue.models import NoiseFilters, NoiseFilterToggles
from ghillie.github.models import GitHubIngestedEvent
from ghillie.github.noise import compile_noise_filters


def test_ignore_authors_drops_matching_author_login() -> None:
    compiled = compile_noise_filters(
        [
            NoiseFilters(
                ignore_authors=["dependabot[bot]"],
            )
        ]
    )
    event = GitHubIngestedEvent(
        event_type="github.pull_request",
        source_event_id="17",
        occurred_at=dt.datetime.now(dt.UTC),
        payload={"author_login": "dependabot[bot]"},
    )
    assert compiled.should_drop(event) is True


def test_ignore_authors_can_be_disabled_per_project() -> None:
    compiled = compile_noise_filters(
        [
            NoiseFilters(
                toggles=NoiseFilterToggles(ignore_authors=False),
                ignore_authors=["dependabot[bot]"],
            )
        ]
    )
    event = GitHubIngestedEvent(
        event_type="github.pull_request",
        source_event_id="17",
        occurred_at=dt.datetime.now(dt.UTC),
        payload={"author_login": "dependabot[bot]"},
    )
    assert compiled.should_drop(event) is False


def test_ignore_title_prefixes_drops_case_insensitive_prefix_match() -> None:
    compiled = compile_noise_filters(
        [
            NoiseFilters(
                ignore_title_prefixes=["chore:"],
            )
        ]
    )
    event = GitHubIngestedEvent(
        event_type="github.issue",
        source_event_id="101",
        occurred_at=dt.datetime.now(dt.UTC),
        payload={"title": "Chore: bump dependencies"},
    )
    assert compiled.should_drop(event) is True


def test_ignore_labels_drops_matching_label() -> None:
    compiled = compile_noise_filters(
        [
            NoiseFilters(
                ignore_labels=["chore/deps"],
            )
        ]
    )
    event = GitHubIngestedEvent(
        event_type="github.pull_request",
        source_event_id="17",
        occurred_at=dt.datetime.now(dt.UTC),
        payload={"labels": ["chore/deps", "ci"]},
    )
    assert compiled.should_drop(event) is True


def test_ignore_paths_drops_matching_doc_change_path_glob() -> None:
    compiled = compile_noise_filters(
        [
            NoiseFilters(
                ignore_paths=["docs/generated/**"],
            )
        ]
    )
    event = GitHubIngestedEvent(
        event_type="github.doc_change",
        source_event_id="abc123:docs/generated/index.md",
        occurred_at=dt.datetime.now(dt.UTC),
        payload={"path": "docs/generated/index.md"},
    )
    assert compiled.should_drop(event) is True
