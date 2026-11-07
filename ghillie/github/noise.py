"""Noise filtering for GitHub ingestion.

Noise filters are authored per project in the estate catalogue. At ingestion
time, the worker compiles the configured filters into an efficient predicate
used to drop low-signal GitHub activity (dependency bots, irrelevant docs
paths, etc.) before persisting to the Bronze layer.
"""

from __future__ import annotations

import dataclasses
import fnmatch
import typing as typ
from pathlib import PurePosixPath

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from ghillie.catalogue.models import NoiseFilters

    from .models import GitHubIngestedEvent


def _normalise_path(path: str) -> str:
    """Normalise a path to POSIX form, trimming surrounding whitespace."""
    stripped = path.strip()
    if not stripped:
        return ""
    # GitHub paths are POSIX-style; normalise any accidental Windows separators
    # before matching glob patterns.
    return PurePosixPath(stripped.replace("\\", "/")).as_posix()


def _normalise_text(value: str) -> str:
    """Trim and lowercase text for case-insensitive comparison."""
    return value.strip().lower()


def _iter_author_candidates(payload: dict[str, typ.Any]) -> cabc.Iterator[str]:
    """Yield the non-blank author login, name and email from a payload."""
    for key in ("author_login", "author_name", "author_email"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            yield value


def _extract_metadata_message(metadata: typ.Any) -> str | None:  # noqa: ANN401
    """Extract message from metadata dict if present and non-empty."""
    if not isinstance(metadata, dict):
        return None

    message = metadata.get("message")
    if not isinstance(message, str) or not message.strip():
        return None

    return message


def _title_for_payload(payload: dict[str, typ.Any]) -> str | None:
    """Return the first non-blank title or message, else the metadata message."""
    for key in ("title", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value

    return _extract_metadata_message(payload.get("metadata"))


def _labels_for_payload(payload: dict[str, typ.Any]) -> list[str]:
    """Return the non-blank string labels from a payload."""
    labels = payload.get("labels")
    if not isinstance(labels, list):
        return []
    return [label for label in labels if isinstance(label, str) and label.strip()]


def _path_for_payload(payload: dict[str, typ.Any]) -> str | None:
    """Return the payload path when it is a non-blank string, else None."""
    value = payload.get("path")
    if isinstance(value, str) and value.strip():
        return value
    return None


@dataclasses.dataclass(frozen=True, slots=True)
class CompiledNoiseFilters:
    """Compiled noise filters ready for ingestion-time evaluation."""

    ignore_authors: frozenset[str] = frozenset()
    ignore_labels: frozenset[str] = frozenset()
    ignore_paths: tuple[str, ...] = ()
    ignore_title_prefixes: tuple[str, ...] = ()

    def should_drop(self, event: GitHubIngestedEvent) -> bool:
        """Return True when the event should be dropped as noise."""
        payload = event.payload
        return (
            self._matches_author(payload)
            or self._matches_label(payload)
            or self._matches_title_prefix(payload)
            or self._matches_path(payload)
        )

    def _matches_author(self, payload: dict[str, typ.Any]) -> bool:
        """Return True when an author field matches an ignored author."""
        if not self.ignore_authors:
            return False
        return any(
            _normalise_text(author) in self.ignore_authors
            for author in _iter_author_candidates(payload)
        )

    def _matches_label(self, payload: dict[str, typ.Any]) -> bool:
        """Return True when any label matches an ignored label."""
        if not self.ignore_labels:
            return False
        return any(
            _normalise_text(label) in self.ignore_labels
            for label in _labels_for_payload(payload)
        )

    def _matches_title_prefix(self, payload: dict[str, typ.Any]) -> bool:
        """Match an ignored prefix against the normalized title.

        The title is the first available of the title, message and metadata
        message, in that order.
        """
        if not self.ignore_title_prefixes:
            return False
        title = _title_for_payload(payload)
        if title is None:
            return False
        lowered = _normalise_text(title)
        return any(lowered.startswith(prefix) for prefix in self.ignore_title_prefixes)

    def _matches_path(self, payload: dict[str, typ.Any]) -> bool:
        """Return True when the path matches an ignored glob pattern."""
        if not self.ignore_paths:
            return False
        path = _path_for_payload(payload)
        if path is None:
            return False
        normalised = _normalise_path(path)
        if not normalised:
            return False
        return any(
            fnmatch.fnmatchcase(normalised, pattern) for pattern in self.ignore_paths
        )


def _merge_author_filters(noise: NoiseFilters, target: set[str]) -> None:
    """Merge author filters into the target set if enabled."""
    if not noise.toggles.ignore_authors:
        return
    target.update(_normalise_text(v) for v in noise.ignore_authors if v.strip())


def _merge_label_filters(noise: NoiseFilters, target: set[str]) -> None:
    """Merge label filters into the target set if enabled."""
    if not noise.toggles.ignore_labels:
        return
    target.update(_normalise_text(v) for v in noise.ignore_labels if v.strip())


def _merge_path_filters(noise: NoiseFilters, target: list[str]) -> None:
    """Merge path filters into the target list if enabled."""
    if not noise.toggles.ignore_paths:
        return
    target.extend(
        _normalise_path(pattern) for pattern in noise.ignore_paths if pattern.strip()
    )


def _merge_title_prefix_filters(noise: NoiseFilters, target: list[str]) -> None:
    """Merge title prefix filters into the target list if enabled."""
    if not noise.toggles.ignore_title_prefixes:
        return
    target.extend(
        _normalise_text(prefix)
        for prefix in noise.ignore_title_prefixes
        if prefix.strip()
    )


def compile_noise_filters(
    project_filters: cabc.Sequence[NoiseFilters],
) -> CompiledNoiseFilters:
    """Compile project noise filter configs into a single predicate.

    When a repository is referenced by multiple projects, all enabled filters
    are merged. Values are normalised to lowercase for text comparisons.
    """
    ignore_authors: set[str] = set()
    ignore_labels: set[str] = set()
    ignore_paths: list[str] = []
    ignore_title_prefixes: list[str] = []

    for noise in project_filters:
        if not noise.enabled:
            continue

        _merge_author_filters(noise, ignore_authors)
        _merge_label_filters(noise, ignore_labels)
        _merge_path_filters(noise, ignore_paths)
        _merge_title_prefix_filters(noise, ignore_title_prefixes)

    # De-dupe whilst preserving configured order for the tuple-based fields.
    dedup_paths = tuple(dict.fromkeys(ignore_paths))
    dedup_prefixes = tuple(dict.fromkeys(ignore_title_prefixes))

    return CompiledNoiseFilters(
        ignore_authors=frozenset(ignore_authors),
        ignore_labels=frozenset(ignore_labels),
        ignore_paths=dedup_paths,
        ignore_title_prefixes=dedup_prefixes,
    )
