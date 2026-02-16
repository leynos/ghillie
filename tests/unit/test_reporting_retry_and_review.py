"""Unit tests for report generation retry and human-review behaviour.

Validates that ``ReportingService.generate_report`` retries when
validation fails, and marks runs for human review after retries are
exhausted.
"""

from __future__ import annotations

import datetime as dt
import typing as typ
from unittest import mock

import pytest
from sqlalchemy import select

from ghillie.evidence import EvidenceBundleService
from ghillie.evidence.models import (
    CommitEvidence,
    ReportStatus,
    RepositoryEvidenceBundle,
    RepositoryMetadata,
)
from ghillie.gold.storage import Report, ReportReview, ReviewState
from ghillie.reporting.config import ReportingConfig
from ghillie.reporting.errors import ReportValidationError
from ghillie.reporting.service import ReportingService, ReportingServiceDependencies
from ghillie.status.models import RepositoryStatusResult

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _valid_result() -> RepositoryStatusResult:
    return RepositoryStatusResult(
        summary="acme/widget is on track with 3 events.",
        status=ReportStatus.ON_TRACK,
        highlights=("Delivered 2 feature PRs",),
    )


def _invalid_result() -> RepositoryStatusResult:
    """Return a result with an empty summary that fails validation."""
    return RepositoryStatusResult(
        summary="",
        status=ReportStatus.ON_TRACK,
        highlights=(),
    )


def _make_bundle(repo_id: str) -> RepositoryEvidenceBundle:
    """Build a minimal bundle for validation/retry tests.

    Uses an empty ``event_fact_ids`` to avoid FK constraint violations
    from synthetic IDs that don't exist in the test database.
    """
    commits = tuple(
        CommitEvidence(sha=f"sha-{i}", message=f"feat: change {i}") for i in range(3)
    )
    return RepositoryEvidenceBundle(
        repository=RepositoryMetadata(
            id=repo_id,
            owner="acme",
            name="widget",
            default_branch="main",
        ),
        window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        commits=commits,
        event_fact_ids=(),
    )


def _build_service(
    session_factory: async_sessionmaker[AsyncSession],
    status_model: mock.AsyncMock,
    *,
    max_attempts: int = 2,
) -> ReportingService:
    """Build a ReportingService with a mock status model."""
    evidence_service = mock.MagicMock(spec=EvidenceBundleService)
    deps = ReportingServiceDependencies(
        session_factory=session_factory,
        evidence_service=evidence_service,
        status_model=status_model,
    )
    config = ReportingConfig(
        window_days=7,
        validation_max_attempts=max_attempts,
    )
    return ReportingService(deps, config=config)


async def _run_failing_report_generation(
    session_factory: async_sessionmaker[AsyncSession],
    max_attempts: int,
) -> str:
    """Run report generation that always fails validation, returning repo_id.

    Creates a test repository, builds a bundle with an invalid status
    model result, and asserts that ``generate_report`` raises
    ``ReportValidationError`` after exhausting *max_attempts*.
    """
    from tests.unit.conftest import create_test_repository

    repo_id = await create_test_repository(session_factory)
    bundle = _make_bundle(repo_id)

    status_model = mock.AsyncMock()
    status_model.summarize_repository = mock.AsyncMock(return_value=_invalid_result())

    service = _build_service(session_factory, status_model, max_attempts=max_attempts)

    with pytest.raises(ReportValidationError):
        await service.generate_report(
            repository_id=repo_id,
            window_start=bundle.window_start,
            window_end=bundle.window_end,
            bundle=bundle,
        )

    return repo_id


class TestGenerateReportRetriesAfterValidationFailure:
    """Service retries status model invocation when validation fails."""

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """First attempt fails validation; second attempt succeeds."""
        from tests.unit.conftest import create_test_repository

        repo_id = await create_test_repository(session_factory)
        bundle = _make_bundle(repo_id)

        status_model = mock.AsyncMock()
        status_model.summarize_repository = mock.AsyncMock(
            side_effect=[_invalid_result(), _valid_result()]
        )

        service = _build_service(session_factory, status_model, max_attempts=2)

        report = await service.generate_report(
            repository_id=repo_id,
            window_start=bundle.window_start,
            window_end=bundle.window_end,
            bundle=bundle,
        )

        assert report is not None
        assert report.human_text == "acme/widget is on track with 3 events."
        assert status_model.summarize_repository.call_count == 2


class TestMarksForHumanReviewAfterExhaustedRetries:
    """Exhausted retries persist a review marker and raise."""

    @pytest.mark.asyncio
    async def test_marks_for_human_review(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """All attempts fail validation; a ReportReview row is created."""
        repo_id = await _run_failing_report_generation(session_factory, max_attempts=2)

        async with session_factory() as session:
            review = await session.scalar(
                select(ReportReview).where(
                    ReportReview.repository_id == repo_id,
                )
            )
            assert review is not None, "Review marker should exist"
            assert review.state == ReviewState.PENDING
            assert review.attempt_count == 2
            assert len(review.validation_issues) >= 1


class TestDoesNotPersistInvalidReport:
    """Invalid reports must never appear in the reports table."""

    @pytest.mark.asyncio
    async def test_no_report_persisted_on_validation_failure(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Assert that no report row exists after validation failure."""
        repo_id = await _run_failing_report_generation(session_factory, max_attempts=1)

        async with session_factory() as session:
            report = await session.scalar(
                select(Report).where(Report.repository_id == repo_id)
            )
            assert report is None, "Invalid report must not be persisted"
