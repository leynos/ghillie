"""Unit tests for EvidenceBundleService."""

# ruff: noqa: PLR0913, FBT001, FBT002

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest

from ghillie.bronze import RawEventEnvelope, RawEventWriter
from ghillie.common.slug import parse_repo_slug
from ghillie.evidence import (
    EvidenceBundleService,
    ReportStatus,
    WorkType,
)
from ghillie.gold import Report, ReportScope
from ghillie.silver import EventFact, RawEventTransformer, Repository

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _commit_event(
    repo_slug: str,
    commit_sha: str,
    occurred_at: dt.datetime,
    message: str = "add feature",
) -> RawEventEnvelope:
    """Create a minimal commit raw event envelope."""
    owner, name = parse_repo_slug(repo_slug)
    return RawEventEnvelope(
        source_system="github",
        source_event_id=f"commit-{commit_sha}",
        event_type="github.commit",
        repo_external_id=repo_slug,
        occurred_at=occurred_at,
        payload={
            "sha": commit_sha,
            "message": message,
            "author_email": "dev@example.com",
            "author_name": "Dev",
            "authored_at": occurred_at.isoformat(),
            "committed_at": occurred_at.isoformat(),
            "repo_owner": owner,
            "repo_name": name,
            "default_branch": "main",
            "metadata": {},
        },
    )


def _pr_event(
    repo_slug: str,
    pr_id: int,
    pr_number: int,
    created_at: dt.datetime,
    title: str = "Add feature",
    state: str = "open",
    labels: list[str] | None = None,
    merged_at: dt.datetime | None = None,
) -> RawEventEnvelope:
    """Create a minimal pull request raw event envelope."""
    owner, name = parse_repo_slug(repo_slug)
    return RawEventEnvelope(
        source_system="github",
        source_event_id=f"pr-{pr_id}",
        event_type="github.pull_request",
        repo_external_id=repo_slug,
        occurred_at=created_at,
        payload={
            "id": pr_id,
            "number": pr_number,
            "title": title,
            "state": state,
            "base_branch": "main",
            "head_branch": "feature",
            "repo_owner": owner,
            "repo_name": name,
            "created_at": created_at.isoformat(),
            "author_login": "dev",
            "merged_at": merged_at.isoformat() if merged_at else None,
            "closed_at": None,
            "labels": labels or [],
            "is_draft": False,
            "metadata": {},
        },
    )


def _issue_event(
    repo_slug: str,
    issue_id: int,
    issue_number: int,
    created_at: dt.datetime,
    title: str = "Bug report",
    state: str = "open",
    labels: list[str] | None = None,
) -> RawEventEnvelope:
    """Create a minimal issue raw event envelope."""
    owner, name = parse_repo_slug(repo_slug)
    return RawEventEnvelope(
        source_system="github",
        source_event_id=f"issue-{issue_id}",
        event_type="github.issue",
        repo_external_id=repo_slug,
        occurred_at=created_at,
        payload={
            "id": issue_id,
            "number": issue_number,
            "title": title,
            "state": state,
            "repo_owner": owner,
            "repo_name": name,
            "created_at": created_at.isoformat(),
            "author_login": "user",
            "closed_at": None,
            "labels": labels or [],
            "metadata": {},
        },
    )


def _doc_change_event(
    repo_slug: str,
    commit_sha: str,
    path: str,
    occurred_at: dt.datetime,
    is_roadmap: bool = False,
) -> RawEventEnvelope:
    """Create a minimal documentation change event."""
    owner, name = parse_repo_slug(repo_slug)
    return RawEventEnvelope(
        source_system="github",
        source_event_id=f"doc-{commit_sha}-{path}",
        event_type="github.doc_change",
        repo_external_id=repo_slug,
        occurred_at=occurred_at,
        payload={
            "commit_sha": commit_sha,
            "path": path,
            "change_type": "modified",
            "repo_owner": owner,
            "repo_name": name,
            "occurred_at": occurred_at.isoformat(),
            "is_roadmap": is_roadmap,
            "is_adr": False,
            "metadata": {},
        },
    )


class TestEvidenceBundleServiceBuildBundle:
    """Tests for EvidenceBundleService.build_bundle."""

    @pytest.mark.asyncio
    async def test_builds_bundle_with_commits(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes commits within the window."""
        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)
        service = EvidenceBundleService(session_factory)

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        # Commit within window
        commit_time = dt.datetime(2024, 7, 5, 10, 0, tzinfo=dt.UTC)
        await writer.ingest(
            _commit_event(repo_slug, "abc123", commit_time, "feat: add feature")
        )
        await transformer.process_pending()

        # Get repo ID
        async with session_factory() as session:
            from sqlalchemy import select

            repo = await session.scalar(select(Repository))
            assert repo is not None
            repo_id = repo.id

        bundle = await service.build_bundle(repo_id, window_start, window_end)

        assert bundle.repository.slug == "octo/reef"
        assert len(bundle.commits) == 1
        assert bundle.commits[0].sha == "abc123"
        assert bundle.commits[0].work_type == WorkType.FEATURE

    @pytest.mark.asyncio
    async def test_builds_bundle_with_prs(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes pull requests created in window."""
        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)
        service = EvidenceBundleService(session_factory)

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        pr_time = dt.datetime(2024, 7, 3, tzinfo=dt.UTC)
        await writer.ingest(
            _pr_event(
                repo_slug, 123, 45, pr_time, title="fix: resolve bug", labels=["bug"]
            )
        )
        await transformer.process_pending()

        async with session_factory() as session:
            from sqlalchemy import select

            repo = await session.scalar(select(Repository))
            assert repo is not None
            repo_id = repo.id

        bundle = await service.build_bundle(repo_id, window_start, window_end)

        assert len(bundle.pull_requests) == 1
        assert bundle.pull_requests[0].number == 45
        assert bundle.pull_requests[0].work_type == WorkType.BUG

    @pytest.mark.asyncio
    async def test_builds_bundle_with_issues(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes issues created in window."""
        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)
        service = EvidenceBundleService(session_factory)

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        issue_time = dt.datetime(2024, 7, 4, tzinfo=dt.UTC)
        await writer.ingest(
            _issue_event(
                repo_slug,
                789,
                12,
                issue_time,
                title="Feature request",
                labels=["enhancement"],
            )
        )
        await transformer.process_pending()

        async with session_factory() as session:
            from sqlalchemy import select

            repo = await session.scalar(select(Repository))
            assert repo is not None
            repo_id = repo.id

        bundle = await service.build_bundle(repo_id, window_start, window_end)

        assert len(bundle.issues) == 1
        assert bundle.issues[0].number == 12
        assert bundle.issues[0].work_type == WorkType.FEATURE

    @pytest.mark.asyncio
    async def test_builds_bundle_with_doc_changes(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes documentation changes in window."""
        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)
        service = EvidenceBundleService(session_factory)

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        doc_time = dt.datetime(2024, 7, 5, tzinfo=dt.UTC)
        # Need a commit first for the doc change
        await writer.ingest(_commit_event(repo_slug, "doc123", doc_time))
        await writer.ingest(
            _doc_change_event(
                repo_slug, "doc123", "docs/roadmap.md", doc_time, is_roadmap=True
            )
        )
        await transformer.process_pending()

        async with session_factory() as session:
            from sqlalchemy import select

            repo = await session.scalar(select(Repository))
            assert repo is not None
            repo_id = repo.id

        bundle = await service.build_bundle(repo_id, window_start, window_end)

        assert len(bundle.documentation_changes) == 1
        assert bundle.documentation_changes[0].path == "docs/roadmap.md"
        assert bundle.documentation_changes[0].is_roadmap is True

    @pytest.mark.asyncio
    async def test_excludes_events_outside_window(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle excludes events outside the window."""
        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)
        service = EvidenceBundleService(session_factory)

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        # Commit before window
        before_time = dt.datetime(2024, 6, 25, tzinfo=dt.UTC)
        await writer.ingest(_commit_event(repo_slug, "before", before_time))

        # Commit in window
        in_time = dt.datetime(2024, 7, 5, tzinfo=dt.UTC)
        await writer.ingest(_commit_event(repo_slug, "during", in_time))

        # Commit after window (at window_end, which is exclusive)
        await writer.ingest(_commit_event(repo_slug, "after", window_end))

        await transformer.process_pending()

        async with session_factory() as session:
            from sqlalchemy import select

            repo = await session.scalar(select(Repository))
            assert repo is not None
            repo_id = repo.id

        bundle = await service.build_bundle(repo_id, window_start, window_end)

        assert len(bundle.commits) == 1
        assert bundle.commits[0].sha == "during"

    @pytest.mark.asyncio
    async def test_includes_previous_reports(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes previous reports for context."""
        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)
        service = EvidenceBundleService(session_factory)

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 15, tzinfo=dt.UTC)

        # Create a commit to establish the repo
        commit_time = dt.datetime(2024, 7, 10, tzinfo=dt.UTC)
        await writer.ingest(_commit_event(repo_slug, "abc123", commit_time))
        await transformer.process_pending()

        async with session_factory() as session:
            from sqlalchemy import select

            repo = await session.scalar(select(Repository))
            assert repo is not None

            # Create a previous report
            prev_report = Report(
                scope=ReportScope.REPOSITORY,
                repository_id=repo.id,
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
            repo_id = repo.id

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
    ) -> None:
        """Bundle computes work type groupings."""
        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)
        service = EvidenceBundleService(session_factory)

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        # Feature commit
        await writer.ingest(
            _commit_event(
                repo_slug,
                "feat1",
                dt.datetime(2024, 7, 2, tzinfo=dt.UTC),
                "feat: add auth",
            )
        )
        # Bug fix commit
        await writer.ingest(
            _commit_event(
                repo_slug,
                "fix1",
                dt.datetime(2024, 7, 3, tzinfo=dt.UTC),
                "fix: resolve crash",
            )
        )
        # Bug PR
        await writer.ingest(
            _pr_event(
                repo_slug,
                100,
                10,
                dt.datetime(2024, 7, 4, tzinfo=dt.UTC),
                title="Fix bug",
                labels=["bug"],
            )
        )
        await transformer.process_pending()

        async with session_factory() as session:
            from sqlalchemy import select

            repo = await session.scalar(select(Repository))
            assert repo is not None
            repo_id = repo.id

        bundle = await service.build_bundle(repo_id, window_start, window_end)

        # Should have groupings for feature and bug
        grouping_map = {g.work_type: g for g in bundle.work_type_groupings}

        assert WorkType.FEATURE in grouping_map
        assert grouping_map[WorkType.FEATURE].commit_count == 1

        assert WorkType.BUG in grouping_map
        assert grouping_map[WorkType.BUG].commit_count == 1
        assert grouping_map[WorkType.BUG].pr_count == 1

    @pytest.mark.asyncio
    async def test_collects_event_fact_ids(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle collects event fact IDs for coverage tracking."""
        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)
        service = EvidenceBundleService(session_factory)

        repo_slug = "octo/reef"
        window_start = dt.datetime(2024, 7, 1, tzinfo=dt.UTC)
        window_end = dt.datetime(2024, 7, 8, tzinfo=dt.UTC)

        commit_time = dt.datetime(2024, 7, 5, tzinfo=dt.UTC)
        await writer.ingest(_commit_event(repo_slug, "abc123", commit_time))
        await transformer.process_pending()

        async with session_factory() as session:
            from sqlalchemy import select

            repo = await session.scalar(select(Repository))
            assert repo is not None
            repo_id = repo.id

            # Verify event facts exist
            facts = (await session.scalars(select(EventFact))).all()
            assert len(facts) == 1

        bundle = await service.build_bundle(repo_id, window_start, window_end)

        assert len(bundle.event_fact_ids) == 1
        assert bundle.event_fact_ids[0] == facts[0].id

    @pytest.mark.asyncio
    async def test_raises_for_missing_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Build raises ValueError for missing repository."""
        service = EvidenceBundleService(session_factory)

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
    ) -> None:
        """Bundle with no events in window is empty."""
        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)
        service = EvidenceBundleService(session_factory)

        repo_slug = "octo/reef"
        # Commit outside window to create repo
        await writer.ingest(
            _commit_event(repo_slug, "abc123", dt.datetime(2024, 6, 1, tzinfo=dt.UTC))
        )
        await transformer.process_pending()

        async with session_factory() as session:
            from sqlalchemy import select

            repo = await session.scalar(select(Repository))
            assert repo is not None
            repo_id = repo.id

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
    ) -> None:
        """Bundle records generation timestamp."""
        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)
        service = EvidenceBundleService(session_factory)

        repo_slug = "octo/reef"
        await writer.ingest(
            _commit_event(repo_slug, "abc123", dt.datetime(2024, 7, 5, tzinfo=dt.UTC))
        )
        await transformer.process_pending()

        async with session_factory() as session:
            from sqlalchemy import select

            repo = await session.scalar(select(Repository))
            assert repo is not None
            repo_id = repo.id

        before = dt.datetime.now(dt.UTC)
        bundle = await service.build_bundle(
            repo_id,
            dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        )
        after = dt.datetime.now(dt.UTC)

        assert bundle.generated_at is not None
        assert before <= bundle.generated_at <= after
