"""Unit tests for EvidenceBundleService."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest

from ghillie.bronze import RawEventWriter
from ghillie.evidence import (
    EvidenceBundleService,
    ReportStatus,
    WorkType,
)
from ghillie.gold import Report, ReportCoverage, ReportProject, ReportScope
from ghillie.silver import EventFact, RawEventTransformer, Repository
from tests.helpers.event_builders import (
    DocChangeEventSpec,
    IssueEventSpec,
    PREventSpec,
    commit_envelope,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Type alias for the evidence service stack fixture
EvidenceServiceStack = tuple[RawEventWriter, RawEventTransformer, EvidenceBundleService]


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def evidence_service_stack(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[RawEventWriter, RawEventTransformer, EvidenceBundleService]:
    """Return writer, transformer, and service instances."""
    return (
        RawEventWriter(session_factory),
        RawEventTransformer(session_factory),
        EvidenceBundleService(session_factory),
    )


async def get_repo_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> str:
    """Query the database and return the repository ID."""
    from sqlalchemy import select

    async with session_factory() as session:
        repo = await session.scalar(select(Repository))
        assert repo is not None
        return repo.id


class TestEvidenceBundleServiceBuildBundle:
    """Tests for EvidenceBundleService.build_bundle."""

    @pytest.mark.asyncio
    async def test_builds_bundle_with_commits(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service_stack: EvidenceServiceStack,
    ) -> None:
        """Bundle includes commits within the window."""
        writer, transformer, service = evidence_service_stack

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        # Commit within window
        commit_time = dt.datetime(2024, 7, 5, 10, 0, tzinfo=dt.UTC)
        await writer.ingest(
            commit_envelope(repo_slug, "abc123", commit_time, "feat: add feature")
        )
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)
        bundle = await service.build_bundle(repo_id, window_start, window_end)

        assert bundle.repository.slug == "octo/reef"
        assert len(bundle.commits) == 1
        assert bundle.commits[0].sha == "abc123"
        assert bundle.commits[0].work_type == WorkType.FEATURE

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "params",
        [
            pytest.param(
                (
                    lambda repo_slug, event_time: PREventSpec(
                        repo_slug=repo_slug,
                        pr_id=123,
                        pr_number=45,
                        created_at=event_time,
                        title="fix: resolve bug",
                        labels=("bug",),
                    ),
                    "pull_requests",
                    45,
                    WorkType.BUG,
                ),
                id="pull_requests",
            ),
            pytest.param(
                (
                    lambda repo_slug, event_time: IssueEventSpec(
                        repo_slug=repo_slug,
                        issue_id=789,
                        issue_number=12,
                        created_at=event_time,
                        title="Feature request",
                        labels=("enhancement",),
                    ),
                    "issues",
                    12,
                    WorkType.FEATURE,
                ),
                id="issues",
            ),
        ],
    )
    async def test_builds_bundle_with_prs_and_issues(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service_stack: EvidenceServiceStack,
        params: tuple[
            typ.Callable[[str, dt.datetime], PREventSpec | IssueEventSpec],
            str,
            int,
            WorkType,
        ],
    ) -> None:
        """Bundle includes pull requests and issues created in window."""
        event_spec, bundle_attr, expected_number, expected_work_type = params
        writer, transformer, service = evidence_service_stack

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        event_time = dt.datetime(2024, 7, 3, tzinfo=dt.UTC)
        await writer.ingest(event_spec(repo_slug, event_time).build())
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)
        bundle = await service.build_bundle(repo_id, window_start, window_end)

        items = getattr(bundle, bundle_attr)
        assert len(items) == 1
        assert items[0].number == expected_number
        assert items[0].work_type == expected_work_type

    @pytest.mark.asyncio
    async def test_builds_bundle_with_doc_changes(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service_stack: EvidenceServiceStack,
    ) -> None:
        """Bundle includes documentation changes in window."""
        writer, transformer, service = evidence_service_stack

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        doc_time = dt.datetime(2024, 7, 5, tzinfo=dt.UTC)
        # Need a commit first for the doc change
        await writer.ingest(commit_envelope(repo_slug, "doc123", doc_time))
        await writer.ingest(
            DocChangeEventSpec(
                repo_slug=repo_slug,
                commit_sha="doc123",
                path="docs/roadmap.md",
                occurred_at=doc_time,
                is_roadmap=True,
            ).build()
        )
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)
        bundle = await service.build_bundle(repo_id, window_start, window_end)

        assert len(bundle.documentation_changes) == 1
        assert bundle.documentation_changes[0].path == "docs/roadmap.md"
        assert bundle.documentation_changes[0].is_roadmap is True

    @pytest.mark.asyncio
    async def test_excludes_events_outside_window(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service_stack: EvidenceServiceStack,
    ) -> None:
        """Bundle excludes events outside the window."""
        writer, transformer, service = evidence_service_stack

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        # Commit before window
        before_time = dt.datetime(2024, 6, 25, tzinfo=dt.UTC)
        await writer.ingest(commit_envelope(repo_slug, "before", before_time))

        # Commit in window
        in_time = dt.datetime(2024, 7, 5, tzinfo=dt.UTC)
        await writer.ingest(commit_envelope(repo_slug, "during", in_time))

        # Commit after window (at window_end, which is exclusive)
        await writer.ingest(commit_envelope(repo_slug, "after", window_end))

        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)
        bundle = await service.build_bundle(repo_id, window_start, window_end)

        assert len(bundle.commits) == 1
        assert bundle.commits[0].sha == "during"

    @pytest.mark.asyncio
    async def test_includes_previous_reports(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service_stack: EvidenceServiceStack,
    ) -> None:
        """Bundle includes previous reports for context."""
        writer, transformer, service = evidence_service_stack

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 15, tzinfo=dt.UTC)

        # Create a commit to establish the repo
        commit_time = dt.datetime(2024, 7, 10, tzinfo=dt.UTC)
        await writer.ingest(commit_envelope(repo_slug, "abc123", commit_time))
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)

        # Create a previous report
        async with session_factory() as session:
            prev_report = Report(
                scope=ReportScope.REPOSITORY,
                repository_id=repo_id,
                window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                model="test-model",
                machine_summary={
                    "status": "on_track",
                    "highlights": ["Shipped v1.0"],
                    "risks": ["Tech debt"],
                },
            )
            session.add(prev_report)
            await session.commit()

        bundle = await service.build_bundle(repo_id, window_start, window_end)

        assert bundle.has_previous_context is True
        assert len(bundle.previous_reports) == 1
        assert bundle.previous_reports[0].status == ReportStatus.ON_TRACK
        assert bundle.previous_reports[0].highlights == ("Shipped v1.0",)
        assert bundle.previous_reports[0].risks == ("Tech debt",)

    @pytest.mark.asyncio
    async def test_computes_work_type_groupings(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service_stack: EvidenceServiceStack,
    ) -> None:
        """Bundle computes work type groupings."""
        writer, transformer, service = evidence_service_stack

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        # Feature commit
        await writer.ingest(
            commit_envelope(
                repo_slug,
                "feat1",
                dt.datetime(2024, 7, 2, tzinfo=dt.UTC),
                "feat: add auth",
            )
        )
        # Bug fix commit
        await writer.ingest(
            commit_envelope(
                repo_slug,
                "fix1",
                dt.datetime(2024, 7, 3, tzinfo=dt.UTC),
                "fix: resolve crash",
            )
        )
        # Bug PR
        await writer.ingest(
            PREventSpec(
                repo_slug=repo_slug,
                pr_id=100,
                pr_number=10,
                created_at=dt.datetime(2024, 7, 4, tzinfo=dt.UTC),
                title="Fix bug",
                labels=("bug",),
            ).build()
        )
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)
        bundle = await service.build_bundle(repo_id, window_start, window_end)

        # Should have groupings for feature and bug
        grouping_map = {g.work_type: g for g in bundle.work_type_groupings}

        assert WorkType.FEATURE in grouping_map
        assert grouping_map[WorkType.FEATURE].commit_count == 1

        assert WorkType.BUG in grouping_map
        assert grouping_map[WorkType.BUG].commit_count == 1
        assert grouping_map[WorkType.BUG].pr_count == 1

    @pytest.mark.asyncio
    async def test_merge_commits_excluded_from_work_type_groupings(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service_stack: EvidenceServiceStack,
    ) -> None:
        """Merge commits are included in bundle but excluded from groupings."""
        writer, transformer, service = evidence_service_stack

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        # Feature commit (non-merge)
        await writer.ingest(
            commit_envelope(
                repo_slug,
                "feat1",
                dt.datetime(2024, 7, 2, tzinfo=dt.UTC),
                "feat: add new feature",
            )
        )
        # Bug fix commit (non-merge)
        await writer.ingest(
            commit_envelope(
                repo_slug,
                "fix1",
                dt.datetime(2024, 7, 3, tzinfo=dt.UTC),
                "fix: resolve bug",
            )
        )
        # Merge commit (should be excluded from groupings)
        await writer.ingest(
            commit_envelope(
                repo_slug,
                "merge1",
                dt.datetime(2024, 7, 4, tzinfo=dt.UTC),
                "Merge pull request #123 from octo/feature-branch",
            )
        )
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)
        bundle = await service.build_bundle(repo_id, window_start, window_end)

        # All 3 commits should be present in the bundle
        assert len(bundle.commits) == 3

        # The merge commit should be flagged as a merge commit
        merge_commits = [c for c in bundle.commits if c.is_merge_commit]
        assert len(merge_commits) == 1
        assert merge_commits[0].sha == "merge1"
        assert "Merge pull request #123" in (merge_commits[0].message or "")

        # Non-merge commits should not be flagged
        non_merge_commits = [c for c in bundle.commits if not c.is_merge_commit]
        assert len(non_merge_commits) == 2

        # Work type groupings should only count non-merge commits
        total_grouped_commit_count = sum(
            g.commit_count for g in bundle.work_type_groupings
        )
        assert total_grouped_commit_count == len(non_merge_commits)

        # Verify the feature and bug groupings each have 1 commit
        grouping_map = {g.work_type: g for g in bundle.work_type_groupings}
        assert WorkType.FEATURE in grouping_map
        assert grouping_map[WorkType.FEATURE].commit_count == 1
        assert WorkType.BUG in grouping_map
        assert grouping_map[WorkType.BUG].commit_count == 1

    @pytest.mark.asyncio
    async def test_collects_event_fact_ids(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service_stack: EvidenceServiceStack,
    ) -> None:
        """Bundle collects event fact IDs for coverage tracking."""
        writer, transformer, service = evidence_service_stack

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        commit_time = dt.datetime(2024, 7, 5, tzinfo=dt.UTC)
        await writer.ingest(commit_envelope(repo_slug, "abc123", commit_time))
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)

        # Verify event facts exist
        async with session_factory() as session:
            from sqlalchemy import select

            facts = (await session.scalars(select(EventFact))).all()
            assert len(facts) == 1

        bundle = await service.build_bundle(repo_id, window_start, window_end)

        assert len(bundle.event_fact_ids) == 1
        assert bundle.event_fact_ids[0] == facts[0].id

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("scope", "expect_exclusion"),
        [
            pytest.param(ReportScope.REPOSITORY, True, id="repository_scope"),
            pytest.param(ReportScope.PROJECT, False, id="project_scope"),
        ],
    )
    async def test_coverage_scope_behavior(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service_stack: EvidenceServiceStack,
        scope: ReportScope,
        *,
        expect_exclusion: bool,
    ) -> None:
        """Bundle applies coverage exclusion by report scope."""
        writer, transformer, service = evidence_service_stack

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        # Two commits in the window
        first_time = dt.datetime(2024, 7, 2, tzinfo=dt.UTC)
        second_time = dt.datetime(2024, 7, 3, tzinfo=dt.UTC)
        await writer.ingest(commit_envelope(repo_slug, "abc123", first_time))
        await writer.ingest(commit_envelope(repo_slug, "def456", second_time))
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)

        async with session_factory() as session:
            from sqlalchemy import select

            facts = (
                await session.scalars(
                    select(EventFact).where(EventFact.event_type == "github.commit")
                )
            ).all()
            covered_fact = next(
                fact for fact in facts if fact.payload.get("sha") == "abc123"
            )

            if scope is ReportScope.REPOSITORY:
                report = Report(
                    scope=scope,
                    repository_id=repo_id,
                    window_start=dt.datetime(2024, 6, 24, tzinfo=dt.UTC),
                    window_end=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                    model="test-model",
                )
                report.coverage_records.append(
                    ReportCoverage(event_fact_id=covered_fact.id)
                )
                session.add(report)
            else:
                project = ReportProject(key="wildside", name="Wildside")
                report = Report(
                    scope=scope,
                    project=project,
                    window_start=dt.datetime(2024, 6, 24, tzinfo=dt.UTC),
                    window_end=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                    model="test-model",
                )
                report.coverage_records.append(
                    ReportCoverage(event_fact_id=covered_fact.id)
                )
                session.add_all([project, report])
            await session.commit()

        bundle = await service.build_bundle(repo_id, window_start, window_end)

        commit_shas = {commit.sha for commit in bundle.commits}
        if expect_exclusion:
            assert "abc123" not in commit_shas
            assert "def456" in commit_shas
            assert covered_fact.id not in set(bundle.event_fact_ids)
        else:
            assert "abc123" in commit_shas
            assert "def456" in commit_shas
            assert covered_fact.id in set(bundle.event_fact_ids)

    @pytest.mark.asyncio
    async def test_pr_issue_coverage_uses_identifier_coercion(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service_stack: EvidenceServiceStack,
    ) -> None:
        """Bundle selects PRs/issues with mixed identifier types and coverage."""
        writer, transformer, service = evidence_service_stack

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        pr_id = 101
        issue_id = 202
        pr_number = 12
        issue_number = 34

        await writer.ingest(
            PREventSpec(
                repo_slug=repo_slug,
                pr_id=pr_id,
                pr_number=pr_number,
                created_at=dt.datetime(2024, 7, 2, tzinfo=dt.UTC),
                title="fix: resolve bug",
                labels=("bug",),
            ).build()
        )
        await writer.ingest(
            PREventSpec(
                repo_slug=repo_slug,
                pr_id=pr_id,
                pr_number=pr_number,
                created_at=dt.datetime(2024, 7, 3, tzinfo=dt.UTC),
                title="fix: resolve bug",
                labels=("bug",),
            ).build()
        )
        await writer.ingest(
            IssueEventSpec(
                repo_slug=repo_slug,
                issue_id=issue_id,
                issue_number=issue_number,
                created_at=dt.datetime(2024, 7, 4, tzinfo=dt.UTC),
                title="Feature request",
                labels=("enhancement",),
            ).build()
        )
        await writer.ingest(
            IssueEventSpec(
                repo_slug=repo_slug,
                issue_id=issue_id,
                issue_number=issue_number,
                created_at=dt.datetime(2024, 7, 5, tzinfo=dt.UTC),
                title="Feature request",
                labels=("enhancement",),
            ).build()
        )
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)

        async with session_factory() as session:
            from sqlalchemy import select

            facts = (
                await session.scalars(
                    select(EventFact).where(
                        EventFact.event_type.in_(
                            ["github.pull_request", "github.issue"]
                        )
                    )
                )
            ).all()
            pr_facts = sorted(
                (fact for fact in facts if fact.event_type == "github.pull_request"),
                key=lambda fact: fact.id,
            )
            issue_facts = sorted(
                (fact for fact in facts if fact.event_type == "github.issue"),
                key=lambda fact: fact.id,
            )
            assert len(pr_facts) == 2
            assert len(issue_facts) == 2

            uncovered_pr_fact = pr_facts[0]
            covered_pr_fact = pr_facts[1]
            uncovered_issue_fact = issue_facts[0]
            covered_issue_fact = issue_facts[1]

            uncovered_pr_fact.payload = {
                **uncovered_pr_fact.payload,
                "id": str(uncovered_pr_fact.payload["id"]),
            }
            uncovered_issue_fact.payload = {
                **uncovered_issue_fact.payload,
                "id": str(uncovered_issue_fact.payload["id"]),
            }

            report = Report(
                scope=ReportScope.REPOSITORY,
                repository_id=repo_id,
                window_start=dt.datetime(2024, 6, 24, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                model="test-model",
            )
            report.coverage_records.append(
                ReportCoverage(event_fact_id=covered_pr_fact.id)
            )
            report.coverage_records.append(
                ReportCoverage(event_fact_id=covered_issue_fact.id)
            )
            session.add(report)
            await session.commit()

        bundle = await service.build_bundle(repo_id, window_start, window_end)

        assert len(bundle.pull_requests) == 1
        assert bundle.pull_requests[0].number == pr_number
        assert len(bundle.issues) == 1
        assert bundle.issues[0].number == issue_number

        event_fact_ids = set(bundle.event_fact_ids)
        assert covered_pr_fact.id not in event_fact_ids
        assert covered_issue_fact.id not in event_fact_ids
        assert uncovered_pr_fact.id in event_fact_ids
        assert uncovered_issue_fact.id in event_fact_ids

    @pytest.mark.asyncio
    async def test_doc_change_coverage_excludes_covered_paths(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service_stack: EvidenceServiceStack,
    ) -> None:
        """Bundle excludes covered documentation changes by commit/path."""
        writer, transformer, service = evidence_service_stack

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        doc_time = dt.datetime(2024, 7, 5, tzinfo=dt.UTC)
        await writer.ingest(commit_envelope(repo_slug, "doc123", doc_time))
        await writer.ingest(
            DocChangeEventSpec(
                repo_slug=repo_slug,
                commit_sha="doc123",
                path="docs/covered.md",
                occurred_at=doc_time,
                is_roadmap=True,
            ).build()
        )
        await writer.ingest(
            DocChangeEventSpec(
                repo_slug=repo_slug,
                commit_sha="doc123",
                path="docs/uncovered.md",
                occurred_at=doc_time,
                is_roadmap=False,
            ).build()
        )
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)

        async with session_factory() as session:
            from sqlalchemy import select

            facts = (
                await session.scalars(
                    select(EventFact).where(EventFact.event_type == "github.doc_change")
                )
            ).all()
            covered_fact = next(
                fact for fact in facts if fact.payload.get("path") == "docs/covered.md"
            )
            report = Report(
                scope=ReportScope.REPOSITORY,
                repository_id=repo_id,
                window_start=dt.datetime(2024, 6, 24, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                model="test-model",
            )
            report.coverage_records.append(
                ReportCoverage(event_fact_id=covered_fact.id)
            )
            session.add(report)
            await session.commit()

        bundle = await service.build_bundle(repo_id, window_start, window_end)

        doc_paths = {doc.path for doc in bundle.documentation_changes}
        assert "docs/covered.md" not in doc_paths
        assert "docs/uncovered.md" in doc_paths
        assert covered_fact.id not in set(bundle.event_fact_ids)

    @pytest.mark.asyncio
    async def test_raises_for_missing_repository(
        self,
        evidence_service_stack: EvidenceServiceStack,
    ) -> None:
        """Build raises ValueError for missing repository."""
        _writer, _transformer, service = evidence_service_stack

        with pytest.raises(ValueError, match="Repository not found"):
            await service.build_bundle(
                "nonexistent-id",
                dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            )

    @pytest.mark.asyncio
    async def test_empty_window_returns_empty_bundle(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service_stack: EvidenceServiceStack,
    ) -> None:
        """Bundle with no events in window is empty."""
        writer, transformer, service = evidence_service_stack

        repo_slug = "octo/reef"
        # Commit outside window to create repo
        await writer.ingest(
            commit_envelope(repo_slug, "abc123", dt.datetime(2024, 6, 1, tzinfo=dt.UTC))
        )
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)

        # Query for a window with no events
        bundle = await service.build_bundle(
            repo_id,
            dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        )

        assert bundle.total_event_count == 0
        assert bundle.commits == ()
        assert bundle.pull_requests == ()
        assert bundle.issues == ()
        assert bundle.documentation_changes == ()
        assert bundle.work_type_groupings == ()

    @pytest.mark.asyncio
    async def test_sets_generated_at(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        evidence_service_stack: EvidenceServiceStack,
    ) -> None:
        """Bundle records generation timestamp."""
        writer, transformer, service = evidence_service_stack

        repo_slug = "octo/reef"
        await writer.ingest(
            commit_envelope(repo_slug, "abc123", dt.datetime(2024, 7, 5, tzinfo=dt.UTC))
        )
        await transformer.process_pending()

        repo_id = await get_repo_id(session_factory)

        before = dt.datetime.now(dt.UTC)
        bundle = await service.build_bundle(
            repo_id,
            dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        )
        after = dt.datetime.now(dt.UTC)

        assert bundle.generated_at is not None
        assert before <= bundle.generated_at <= after
