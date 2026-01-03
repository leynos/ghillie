"""Work type classification based on labels and title heuristics."""

from __future__ import annotations

import functools
import re
import typing as typ

import msgspec

from .models import WorkType

if typ.TYPE_CHECKING:
    from ghillie.silver.storage import Commit


@typ.runtime_checkable
class Classifiable(typ.Protocol):
    """Protocol for entities that can be classified by labels and title.

    Any entity with labels and title attributes can be classified.
    """

    @property
    def labels(self) -> typ.Sequence[str]:
        """Labels attached to the entity."""
        ...

    @property
    def title(self) -> str:
        """Title of the entity."""
        ...


@functools.lru_cache(maxsize=32)
def _compile_patterns(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    """Compile a tuple of regex pattern strings into Pattern objects.

    Results are cached by pattern tuple for efficient reuse across calls.
    """
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


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

    @property
    def compiled_feature_patterns(self) -> tuple[re.Pattern[str], ...]:
        """Return compiled feature title patterns (cached via lru_cache)."""
        return _compile_patterns(self.feature_title_patterns)

    @property
    def compiled_bug_patterns(self) -> tuple[re.Pattern[str], ...]:
        """Return compiled bug title patterns (cached via lru_cache)."""
        return _compile_patterns(self.bug_title_patterns)

    @property
    def compiled_refactor_patterns(self) -> tuple[re.Pattern[str], ...]:
        """Return compiled refactor title patterns (cached via lru_cache)."""
        return _compile_patterns(self.refactor_title_patterns)

    @property
    def compiled_chore_patterns(self) -> tuple[re.Pattern[str], ...]:
        """Return compiled chore title patterns (cached via lru_cache)."""
        return _compile_patterns(self.chore_title_patterns)


# Default configuration instance
DEFAULT_CLASSIFICATION_CONFIG = ClassificationConfig()


def _normalise_label(label: str) -> str:
    """Normalise a label for comparison."""
    return label.strip().lower()


def _labels_match(labels: typ.Sequence[str], patterns: tuple[str, ...]) -> bool:
    """Check if any label matches the pattern set."""
    normalised_patterns = {_normalise_label(p) for p in patterns}
    return any(_normalise_label(label) in normalised_patterns for label in labels)


def _title_matches_compiled(title: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    """Check if title matches any precompiled regex pattern."""
    lowered = title.lower()
    return any(pattern.search(lowered) for pattern in patterns)


def _prefix_only_compiled(
    patterns: tuple[re.Pattern[str], ...],
) -> tuple[re.Pattern[str], ...]:
    """Filter to keep only patterns that start with ^."""
    return tuple(p for p in patterns if p.pattern.startswith("^"))


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


def _classify_by_prefix_patterns(
    title: str,
    config: ClassificationConfig,
) -> WorkType | None:
    """Classify by prefix patterns (conventional commits).

    Order: bug > chore > feature > refactor
    (Chore before feature so "ci: fix X" is CHORE not BUG)
    """
    bug_prefixes = _prefix_only_compiled(config.compiled_bug_patterns)
    if _title_matches_compiled(title, bug_prefixes):
        return WorkType.BUG
    chore_prefixes = _prefix_only_compiled(config.compiled_chore_patterns)
    if _title_matches_compiled(title, chore_prefixes):
        return WorkType.CHORE
    feature_prefixes = _prefix_only_compiled(config.compiled_feature_patterns)
    if _title_matches_compiled(title, feature_prefixes):
        return WorkType.FEATURE
    refactor_prefixes = _prefix_only_compiled(config.compiled_refactor_patterns)
    if _title_matches_compiled(title, refactor_prefixes):
        return WorkType.REFACTOR
    return None


def _classify_by_general_patterns(
    title: str,
    config: ClassificationConfig,
) -> WorkType | None:
    """Classify by general patterns.

    Order: bug > feature > refactor > chore
    (Bug first as it typically requires immediate attention;
    chore last as it's the least specific category)
    """
    if _title_matches_compiled(title, config.compiled_bug_patterns):
        return WorkType.BUG
    if _title_matches_compiled(title, config.compiled_feature_patterns):
        return WorkType.FEATURE
    if _title_matches_compiled(title, config.compiled_refactor_patterns):
        return WorkType.REFACTOR
    if _title_matches_compiled(title, config.compiled_chore_patterns):
        return WorkType.CHORE
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

    # First check prefix patterns (conventional commits), then general patterns
    return _classify_by_prefix_patterns(title, config) or _classify_by_general_patterns(
        title, config
    )


def _classify_by_labels_then_title(
    labels: typ.Sequence[str],
    title: str | None,
    config: ClassificationConfig = DEFAULT_CLASSIFICATION_CONFIG,
) -> WorkType:
    """Classify work type by labels then title, with UNKNOWN as fallback.

    Labels take precedence because they represent explicit author intent.

    Parameters
    ----------
    labels
        Sequence of labels to check.
    title
        Title or message to check.
    config
        Classification configuration.

    Returns
    -------
    WorkType
        The classified work type.

    """
    by_labels = classify_by_labels(labels, config)
    if by_labels is not None:
        return by_labels

    by_title = classify_by_title(title, config)
    if by_title is not None:
        return by_title

    return WorkType.UNKNOWN


def classify_entity(
    entity: Classifiable,
    config: ClassificationConfig = DEFAULT_CLASSIFICATION_CONFIG,
) -> WorkType:
    """Classify an entity (PR or issue) by labels then title.

    Labels take precedence because they represent explicit author intent.

    Parameters
    ----------
    entity
        Any object with labels and title attributes (e.g. PullRequest, Issue).
    config
        Classification configuration.

    Returns
    -------
    WorkType
        The classified work type.

    """
    return _classify_by_labels_then_title(entity.labels, entity.title, config)


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
