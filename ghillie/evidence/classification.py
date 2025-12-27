"""Work type classification based on labels and title heuristics."""

from __future__ import annotations

import re
import typing as typ

import msgspec

from .models import WorkType

if typ.TYPE_CHECKING:
    from ghillie.silver.storage import Commit, Issue, PullRequest


class ClassificationConfig(msgspec.Struct, kw_only=True, frozen=True):
    """Configurable rules for work type classification.

    Attributes
    ----------
    feature_labels
        Labels that indicate a feature.
    bug_labels
        Labels that indicate a bug fix.
    refactor_labels
        Labels that indicate refactoring.
    chore_labels
        Labels that indicate chores/maintenance.
    documentation_labels
        Labels that indicate documentation work.
    feature_title_patterns
        Regex patterns in titles that indicate features.
    bug_title_patterns
        Regex patterns in titles that indicate bugs.
    refactor_title_patterns
        Regex patterns in titles that indicate refactoring.
    chore_title_patterns
        Regex patterns in titles that indicate chores.

    """

    feature_labels: tuple[str, ...] = (
        "feature",
        "enhancement",
        "new feature",
        "feat",
    )
    bug_labels: tuple[str, ...] = (
        "bug",
        "bugfix",
        "fix",
        "defect",
        "hotfix",
    )
    refactor_labels: tuple[str, ...] = (
        "refactor",
        "refactoring",
        "tech debt",
        "technical debt",
        "cleanup",
    )
    chore_labels: tuple[str, ...] = (
        "chore",
        "maintenance",
        "dependencies",
        "deps",
        "ci",
        "build",
    )
    documentation_labels: tuple[str, ...] = (
        "documentation",
        "docs",
        "doc",
    )
    feature_title_patterns: tuple[str, ...] = (
        r"^feat(\(.+\))?:",
        r"^add\s",
        r"^implement\s",
        r"^introduce\s",
    )
    bug_title_patterns: tuple[str, ...] = (
        r"^fix(\(.+\))?:",
        r"^bugfix:",
        r"^hotfix:",
        # Match "fix/fixes/fixed" as standalone words, but not after a hyphen
        r"(?<![a-zA-Z-])fix(es|ed)?(?![a-zA-Z])",
    )
    refactor_title_patterns: tuple[str, ...] = (
        r"^refactor(\(.+\))?:",
        r"\brefactor\b",
        r"\bcleanup\b",
    )
    chore_title_patterns: tuple[str, ...] = (
        r"^chore(\(.+\))?:",
        r"^ci(\(.+\))?:",
        r"^build(\(.+\))?:",
        r"\bdependenc(y|ies)\b",
        r"\bbump\b",
        r"^update\s+.*dependenc",  # "update dependency versions", etc.
    )


# Default configuration instance
DEFAULT_CLASSIFICATION_CONFIG = ClassificationConfig()


def _normalise_label(label: str) -> str:
    """Normalise a label for comparison."""
    return label.strip().lower()


def _labels_match(labels: typ.Sequence[str], patterns: tuple[str, ...]) -> bool:
    """Check if any label matches the pattern set."""
    normalised_patterns = {_normalise_label(p) for p in patterns}
    return any(_normalise_label(label) in normalised_patterns for label in labels)


def _title_matches(title: str | None, patterns: tuple[str, ...]) -> bool:
    """Check if title matches any regex pattern."""
    if title is None:
        return False
    lowered = title.lower()
    return any(re.search(pattern, lowered, re.IGNORECASE) for pattern in patterns)


def classify_by_labels(
    labels: typ.Sequence[str],
    config: ClassificationConfig = DEFAULT_CLASSIFICATION_CONFIG,
) -> WorkType | None:
    """Classify work type by labels, returning None if no match.

    Parameters
    ----------
    labels
        Sequence of labels to check.
    config
        Classification configuration with label patterns.

    Returns
    -------
    WorkType | None
        The classified work type, or None if no match.

    """
    # Order matters: more specific types first
    if _labels_match(labels, config.bug_labels):
        return WorkType.BUG
    if _labels_match(labels, config.feature_labels):
        return WorkType.FEATURE
    if _labels_match(labels, config.refactor_labels):
        return WorkType.REFACTOR
    if _labels_match(labels, config.documentation_labels):
        return WorkType.DOCUMENTATION
    if _labels_match(labels, config.chore_labels):
        return WorkType.CHORE
    return None


def _matches_prefix_pattern(title: str, patterns: tuple[str, ...]) -> bool:
    """Check if title matches any prefix pattern (starting with ^)."""
    lowered = title.lower()
    return any(
        pattern.startswith("^") and re.search(pattern, lowered, re.IGNORECASE)
        for pattern in patterns
    )


def _classify_title_by_patterns(
    title: str,
    pattern_groups: tuple[tuple[tuple[str, ...], WorkType], ...],
    *,
    prefix_only: bool = False,
) -> WorkType | None:
    """Classify title by matching against pattern groups in order."""
    for patterns, work_type in pattern_groups:
        if prefix_only:
            if _matches_prefix_pattern(title, patterns):
                return work_type
        elif _title_matches(title, patterns):
            return work_type
    return None


def classify_by_title(
    title: str | None,
    config: ClassificationConfig = DEFAULT_CLASSIFICATION_CONFIG,
) -> WorkType | None:
    """Classify work type by title patterns, returning None if no match.

    Parameters
    ----------
    title
        Title or message to check.
    config
        Classification configuration with title patterns.

    Returns
    -------
    WorkType | None
        The classified work type, or None if no match.

    """
    if title is None:
        return None

    # Define pattern groups with priority order
    # Prefix patterns: bug > chore > feature > refactor
    # (Chore before feature so "ci: fix X" is CHORE not BUG)
    prefix_order: tuple[tuple[tuple[str, ...], WorkType], ...] = (
        (config.bug_title_patterns, WorkType.BUG),
        (config.chore_title_patterns, WorkType.CHORE),
        (config.feature_title_patterns, WorkType.FEATURE),
        (config.refactor_title_patterns, WorkType.REFACTOR),
    )

    # General patterns: bug > feature > refactor > chore
    general_order: tuple[tuple[tuple[str, ...], WorkType], ...] = (
        (config.bug_title_patterns, WorkType.BUG),
        (config.feature_title_patterns, WorkType.FEATURE),
        (config.refactor_title_patterns, WorkType.REFACTOR),
        (config.chore_title_patterns, WorkType.CHORE),
    )

    # First check prefix patterns (conventional commits), then general patterns
    return _classify_title_by_patterns(
        title, prefix_order, prefix_only=True
    ) or _classify_title_by_patterns(title, general_order)


def classify_pull_request(
    pr: PullRequest,
    config: ClassificationConfig = DEFAULT_CLASSIFICATION_CONFIG,
) -> WorkType:
    """Classify a pull request by labels then title.

    Labels take precedence because they represent explicit author intent.

    Parameters
    ----------
    pr
        The pull request to classify.
    config
        Classification configuration.

    Returns
    -------
    WorkType
        The classified work type.

    """
    # Labels take precedence
    by_labels = classify_by_labels(pr.labels, config)
    if by_labels is not None:
        return by_labels

    # Fall back to title heuristics
    by_title = classify_by_title(pr.title, config)
    if by_title is not None:
        return by_title

    return WorkType.UNKNOWN


def classify_issue(
    issue: Issue,
    config: ClassificationConfig = DEFAULT_CLASSIFICATION_CONFIG,
) -> WorkType:
    """Classify an issue by labels then title.

    Labels take precedence because they represent explicit author intent.

    Parameters
    ----------
    issue
        The issue to classify.
    config
        Classification configuration.

    Returns
    -------
    WorkType
        The classified work type.

    """
    by_labels = classify_by_labels(issue.labels, config)
    if by_labels is not None:
        return by_labels

    by_title = classify_by_title(issue.title, config)
    if by_title is not None:
        return by_title

    return WorkType.UNKNOWN


def classify_commit(
    commit: Commit,
    config: ClassificationConfig = DEFAULT_CLASSIFICATION_CONFIG,
) -> WorkType:
    """Classify a commit by its message.

    Parameters
    ----------
    commit
        The commit to classify.
    config
        Classification configuration.

    Returns
    -------
    WorkType
        The classified work type.

    """
    by_title = classify_by_title(commit.message, config)
    if by_title is not None:
        return by_title
    return WorkType.UNKNOWN


def is_merge_commit(commit: Commit) -> bool:
    """Determine if a commit appears to be a merge commit.

    Parameters
    ----------
    commit
        The commit to check.

    Returns
    -------
    bool
        True if the commit appears to be a merge commit.

    """
    if commit.message is None:
        return False
    lowered = commit.message.lower()
    return lowered.startswith("merge ") or lowered.startswith("merge pull request")
