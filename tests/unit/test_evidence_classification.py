"""Unit tests for work type classification logic."""

# ruff: noqa: D102

from __future__ import annotations

from unittest import mock

from ghillie.evidence import (
    ClassificationConfig,
    WorkType,
    classify_by_labels,
    classify_by_title,
    classify_commit,
    classify_issue,
    classify_pull_request,
    is_merge_commit,
)


class TestClassifyByLabels:
    """Tests for label-based classification."""

    def test_bug_label_match(self) -> None:
        assert classify_by_labels(["bug"]) == WorkType.BUG
        assert classify_by_labels(["bugfix"]) == WorkType.BUG
        assert classify_by_labels(["fix"]) == WorkType.BUG
        assert classify_by_labels(["defect"]) == WorkType.BUG
        assert classify_by_labels(["hotfix"]) == WorkType.BUG

    def test_feature_label_match(self) -> None:
        assert classify_by_labels(["feature"]) == WorkType.FEATURE
        assert classify_by_labels(["enhancement"]) == WorkType.FEATURE
        assert classify_by_labels(["new feature"]) == WorkType.FEATURE
        assert classify_by_labels(["feat"]) == WorkType.FEATURE

    def test_refactor_label_match(self) -> None:
        assert classify_by_labels(["refactor"]) == WorkType.REFACTOR
        assert classify_by_labels(["refactoring"]) == WorkType.REFACTOR
        assert classify_by_labels(["tech debt"]) == WorkType.REFACTOR
        assert classify_by_labels(["cleanup"]) == WorkType.REFACTOR

    def test_chore_label_match(self) -> None:
        assert classify_by_labels(["chore"]) == WorkType.CHORE
        assert classify_by_labels(["maintenance"]) == WorkType.CHORE
        assert classify_by_labels(["dependencies"]) == WorkType.CHORE
        assert classify_by_labels(["deps"]) == WorkType.CHORE
        assert classify_by_labels(["ci"]) == WorkType.CHORE
        assert classify_by_labels(["build"]) == WorkType.CHORE

    def test_documentation_label_match(self) -> None:
        assert classify_by_labels(["documentation"]) == WorkType.DOCUMENTATION
        assert classify_by_labels(["docs"]) == WorkType.DOCUMENTATION
        assert classify_by_labels(["doc"]) == WorkType.DOCUMENTATION

    def test_no_match_returns_none(self) -> None:
        assert classify_by_labels([]) is None
        assert classify_by_labels(["random"]) is None
        assert classify_by_labels(["priority:high"]) is None

    def test_case_insensitive(self) -> None:
        assert classify_by_labels(["BUG"]) == WorkType.BUG
        assert classify_by_labels(["Feature"]) == WorkType.FEATURE
        assert classify_by_labels(["REFACTOR"]) == WorkType.REFACTOR

    def test_whitespace_handling(self) -> None:
        assert classify_by_labels(["  bug  "]) == WorkType.BUG
        assert classify_by_labels([" enhancement "]) == WorkType.FEATURE

    def test_bug_takes_priority_over_feature(self) -> None:
        # Bug is more specific, so it should win
        assert classify_by_labels(["bug", "feature"]) == WorkType.BUG

    def test_custom_config(self) -> None:
        config = ClassificationConfig(
            feature_labels=("new-stuff",),
            bug_labels=("broken",),
        )
        assert classify_by_labels(["new-stuff"], config) == WorkType.FEATURE
        assert classify_by_labels(["broken"], config) == WorkType.BUG
        # Default labels should not match with custom config
        assert classify_by_labels(["feature"], config) is None


class TestClassifyByTitle:
    """Tests for title/message pattern-based classification."""

    def test_conventional_commit_bug_patterns(self) -> None:
        assert classify_by_title("fix: resolve login issue") == WorkType.BUG
        assert classify_by_title("fix(auth): handle null token") == WorkType.BUG
        assert classify_by_title("bugfix: correct calculation") == WorkType.BUG
        assert classify_by_title("hotfix: emergency patch") == WorkType.BUG

    def test_conventional_commit_feature_patterns(self) -> None:
        assert classify_by_title("feat: add dark mode") == WorkType.FEATURE
        assert classify_by_title("feat(ui): implement sidebar") == WorkType.FEATURE
        assert classify_by_title("add new payment method") == WorkType.FEATURE
        assert classify_by_title("implement caching layer") == WorkType.FEATURE
        assert classify_by_title("introduce rate limiting") == WorkType.FEATURE

    def test_conventional_commit_refactor_patterns(self) -> None:
        assert classify_by_title("refactor: clean up auth module") == WorkType.REFACTOR
        assert classify_by_title("refactor(db): simplify queries") == WorkType.REFACTOR
        assert classify_by_title("cleanup unused imports") == WorkType.REFACTOR

    def test_conventional_commit_chore_patterns(self) -> None:
        assert classify_by_title("chore: update dependencies") == WorkType.CHORE
        assert classify_by_title("ci: fix pipeline") == WorkType.CHORE
        assert classify_by_title("build: upgrade webpack") == WorkType.CHORE
        assert classify_by_title("bump version to 2.0") == WorkType.CHORE
        assert classify_by_title("update dependency versions") == WorkType.CHORE

    def test_word_boundary_fix_pattern(self) -> None:
        # "fix" should match as a word, not as part of another word
        assert classify_by_title("This fixes the bug") == WorkType.BUG
        assert classify_by_title("Fixed the issue") == WorkType.BUG
        # But shouldn't match in prefix
        assert classify_by_title("prefix-fix") is None

    def test_no_match_returns_none(self) -> None:
        assert classify_by_title(None) is None
        assert classify_by_title("") is None
        assert classify_by_title("Update README") is None
        assert classify_by_title("Merge branch main") is None

    def test_case_insensitive(self) -> None:
        assert classify_by_title("FIX: resolve issue") == WorkType.BUG
        assert classify_by_title("FEAT: add feature") == WorkType.FEATURE
        assert classify_by_title("REFACTOR: clean up") == WorkType.REFACTOR

    def test_bug_takes_priority(self) -> None:
        # "fix" pattern should match before feature patterns
        assert classify_by_title("fix: add error handling") == WorkType.BUG


class TestClassifyPullRequest:
    """Tests for pull request classification."""

    def test_label_takes_priority_over_title(self) -> None:
        pr = mock.MagicMock()
        pr.labels = ["feature"]
        pr.title = "fix: resolve issue"

        # Label says feature, title says bug - label wins
        assert classify_pull_request(pr) == WorkType.FEATURE

    def test_falls_back_to_title(self) -> None:
        pr = mock.MagicMock()
        pr.labels = ["priority:high"]  # No work type label
        pr.title = "feat: add new feature"

        assert classify_pull_request(pr) == WorkType.FEATURE

    def test_returns_unknown_when_no_match(self) -> None:
        pr = mock.MagicMock()
        pr.labels = []
        pr.title = "Update configuration"

        assert classify_pull_request(pr) == WorkType.UNKNOWN

    def test_custom_config(self) -> None:
        config = ClassificationConfig(feature_labels=("new-work",))

        pr = mock.MagicMock()
        pr.labels = ["new-work"]
        pr.title = "Some change"

        assert classify_pull_request(pr, config) == WorkType.FEATURE


class TestClassifyIssue:
    """Tests for issue classification."""

    def test_label_takes_priority(self) -> None:
        issue = mock.MagicMock()
        issue.labels = ["bug"]
        issue.title = "Feature request: dark mode"

        assert classify_issue(issue) == WorkType.BUG

    def test_falls_back_to_title(self) -> None:
        issue = mock.MagicMock()
        issue.labels = []
        issue.title = "Fix the login page"

        assert classify_issue(issue) == WorkType.BUG

    def test_returns_unknown_when_no_match(self) -> None:
        issue = mock.MagicMock()
        issue.labels = []
        issue.title = "Question about API"

        assert classify_issue(issue) == WorkType.UNKNOWN


class TestClassifyCommit:
    """Tests for commit classification."""

    def test_classifies_by_message(self) -> None:
        commit = mock.MagicMock()
        commit.message = "feat: implement user auth"

        assert classify_commit(commit) == WorkType.FEATURE

    def test_returns_unknown_for_no_match(self) -> None:
        commit = mock.MagicMock()
        commit.message = "Update README"

        assert classify_commit(commit) == WorkType.UNKNOWN

    def test_handles_none_message(self) -> None:
        commit = mock.MagicMock()
        commit.message = None

        assert classify_commit(commit) == WorkType.UNKNOWN


class TestIsMergeCommit:
    """Tests for merge commit detection."""

    def test_detects_merge_commit(self) -> None:
        commit = mock.MagicMock()
        commit.message = "Merge branch 'feature' into main"

        assert is_merge_commit(commit) is True

    def test_detects_merge_pull_request(self) -> None:
        commit = mock.MagicMock()
        commit.message = "Merge pull request #123 from user/branch"

        assert is_merge_commit(commit) is True

    def test_case_insensitive(self) -> None:
        commit = mock.MagicMock()
        commit.message = "MERGE BRANCH 'feature'"

        assert is_merge_commit(commit) is True

    def test_non_merge_commit(self) -> None:
        commit = mock.MagicMock()
        commit.message = "feat: add feature"

        assert is_merge_commit(commit) is False

    def test_merge_in_middle_is_not_merge_commit(self) -> None:
        commit = mock.MagicMock()
        commit.message = "fix: merge conflict resolution"

        assert is_merge_commit(commit) is False

    def test_handles_none_message(self) -> None:
        commit = mock.MagicMock()
        commit.message = None

        assert is_merge_commit(commit) is False
