"""Behavioural coverage for report validation and retry workflow."""

from __future__ import annotations

import asyncio
import dataclasses as dc
import datetime as dt
import typing as typ
from unittest import mock

import falcon.testing
from pytest_bdd import given, scenario, then, when
from sqlalchemy import select

from ghillie.api.app import AppDependencies, create_app
from ghillie.bronze import RawEventWriter
from ghillie.evidence import EvidenceBundleService
from ghillie.evidence.models import ReportStatus
from ghillie.gold.storage import Report, ReportReview, ReviewState
from ghillie.reporting import (
    ReportingConfig,
    ReportingService,
    ReportingServiceDependencies,
)
from ghillie.reporting.errors import ReportValidationError
from ghillie.silver import RawEventTransformer, Repository
from ghillie.status.models import RepositoryStatusResult
from tests.helpers.event_builders import commit_envelope

if typ.TYPE_CHECKING:
    from falcon.testing.client import Result
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dc.dataclass(frozen=True, kw_only=True)
class RepoSetupParams:
    """Configuration for repository setup in validation tests."""

    status_model_behavior: dict[str, object]
    commit_id: str
    commit_message: str
    max_attempts: int = 2
    include_client: bool = False


def _valid_result() -> RepositoryStatusResult:
    return RepositoryStatusResult(
        summary="acme/widgets is on track with 1 events.",
        status=ReportStatus.ON_TRACK,
        highlights=("Did a thing",),
    )


def _invalid_result() -> RepositoryStatusResult:
    return RepositoryStatusResult(
        summary="",
        status=ReportStatus.ON_TRACK,
        highlights=(),
    )


def _build_reporting_service(
    session_factory: async_sessionmaker[AsyncSession],
    status_model: object,
    *,
    max_attempts: int = 2,
) -> ReportingService:
    deps = ReportingServiceDependencies(
        session_factory=session_factory,
        evidence_service=EvidenceBundleService(session_factory),
        # AsyncMock satisfies the protocol at runtime but not statically.
        status_model=status_model,  # type: ignore[arg-type]
    )
    config = ReportingConfig(
        window_days=7,
        validation_max_attempts=max_attempts,
    )
    return ReportingService(deps, config=config)


class ValidationContext(typ.TypedDict, total=False):
    """Mutable context shared between validation scenario steps."""

    session_factory: async_sessionmaker[AsyncSession]
    service: ReportingService
    status_model: mock.AsyncMock
    repo_id: str
    report: Report | None
    error: ReportValidationError | None
    client: falcon.testing.TestClient
    response: Result


def _setup_repo_with_status_model(
    session_factory: async_sessionmaker[AsyncSession],
    params: RepoSetupParams,
) -> ValidationContext:
    """Set up repository with configured status model behavior."""
    status_model = mock.AsyncMock()
    status_model.summarize_repository = mock.AsyncMock(**params.status_model_behavior)  # type: ignore[arg-type]

    service = _build_reporting_service(
        session_factory, status_model, max_attempts=params.max_attempts
    )

    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)

    async def _setup() -> str:
        commit_time = dt.datetime.now(dt.UTC) - dt.timedelta(days=2)
        await writer.ingest(
            commit_envelope(
                "acme/widgets",
                params.commit_id,
                commit_time,
                params.commit_message,
            )
        )
        await transformer.process_pending()
        async with session_factory() as session:
            repo = await session.scalar(select(Repository))
            assert repo is not None, "Repository should exist after ingest + transform"
            return repo.id

    repo_id = asyncio.run(_setup())

    ctx: ValidationContext = {
        "session_factory": session_factory,
        "service": service,
        "status_model": status_model,
        "repo_id": repo_id,
    }

    if params.include_client:
        deps = AppDependencies(
            session_factory=session_factory,
            reporting_service=service,
        )
        ctx["client"] = falcon.testing.TestClient(create_app(deps))

    return ctx


# -- Scenario wrappers -------------------------------------------------------


@scenario(
    "../report_validation.feature",
    "Retry succeeds after initial validation failure",
)
def test_retry_succeeds_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


@scenario(
    "../report_validation.feature",
    "Mark for human review after retries exhausted",
)
def test_mark_for_review_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


@scenario(
    "../report_validation.feature",
    "API returns 422 for validation failure",
)
def test_api_422_scenario() -> None:
    """Wrapper for pytest-bdd scenario."""


# -- Given steps --------------------------------------------------------------


@given(
    "a repository with events and a status model that fails then succeeds",
    target_fixture="validation_context",
)
def given_repo_with_retry_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> ValidationContext:
    """Set up a repo with a status model that fails once, then succeeds."""
    params = RepoSetupParams(
        status_model_behavior={"side_effect": [_invalid_result(), _valid_result()]},
        commit_id="abc123",
        commit_message="Initial commit",
    )
    return _setup_repo_with_status_model(session_factory, params)


@given(
    "a repository with events and a status model that always fails validation",
    target_fixture="validation_context",
)
def given_repo_always_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> ValidationContext:
    """Set up a repo whose status model always returns invalid results."""
    params = RepoSetupParams(
        status_model_behavior={"return_value": _invalid_result()},
        commit_id="def456",
        commit_message="Second commit",
    )
    return _setup_repo_with_status_model(session_factory, params)


@given(
    "a running API with a status model that always fails validation",
    target_fixture="validation_context",
)
def given_api_always_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> ValidationContext:
    """Set up an API whose status model always produces invalid results."""
    params = RepoSetupParams(
        status_model_behavior={"return_value": _invalid_result()},
        commit_id="ghi789",
        commit_message="Third commit",
        include_client=True,
    )
    return _setup_repo_with_status_model(session_factory, params)


# -- When steps ---------------------------------------------------------------


@when("I run the reporting service for the repository")
def when_run_service(validation_context: ValidationContext) -> None:
    """Run the reporting service expecting success."""

    async def _run() -> Report | None:
        service = validation_context["service"]
        repo_id = validation_context["repo_id"]
        return await service.run_for_repository(repo_id)

    report = asyncio.run(_run())
    validation_context["report"] = report


@when("I run the reporting service expecting failure")
def when_run_service_expecting_failure(
    validation_context: ValidationContext,
) -> None:
    """Run the reporting service expecting ReportValidationError."""

    async def _run() -> ReportValidationError | None:
        service = validation_context["service"]
        repo_id = validation_context["repo_id"]
        try:
            await service.run_for_repository(repo_id)
        except ReportValidationError as exc:
            return exc
        return None

    error = asyncio.run(_run())
    validation_context["error"] = error


@when("I POST to trigger report generation")
def when_post_trigger(validation_context: ValidationContext) -> None:
    """POST to the report endpoint."""
    client = validation_context["client"]
    validation_context["response"] = client.simulate_post(
        "/reports/repositories/acme/widgets"
    )


# -- Then steps ---------------------------------------------------------------


@then("a valid Gold report is persisted")
def then_report_persisted(validation_context: ValidationContext) -> None:
    """Assert the report was persisted after retry."""
    report = validation_context["report"]
    assert report is not None, "Report should exist after successful retry"
    assert report.human_text, "Report should have non-empty human_text"


@then("the status model was invoked twice")
def then_status_model_called_twice(
    validation_context: ValidationContext,
) -> None:
    """Assert the mock status model was called twice (initial + retry)."""
    status_model = validation_context["status_model"]
    count = status_model.summarize_repository.call_count
    assert count == 2, f"expected summarize_repository to be called twice, got {count}"


@then("a human-review marker is created for the repository")
def then_review_marker_created(
    validation_context: ValidationContext,
) -> None:
    """Assert a ReportReview row exists for this repository."""

    async def _check() -> None:
        sf = validation_context["session_factory"]
        repo_id = validation_context["repo_id"]
        async with sf() as session:
            review = await session.scalar(
                select(ReportReview).where(
                    ReportReview.repository_id == repo_id,
                )
            )
            assert review is not None, "Review marker should exist for the repository"
            assert review.state == ReviewState.PENDING, (
                f"expected review.state to be PENDING, got {review.state}"
            )

    asyncio.run(_check())


@then("no report is persisted")
def then_no_report(validation_context: ValidationContext) -> None:
    """Assert no Report rows were created."""

    async def _check() -> None:
        sf = validation_context["session_factory"]
        repo_id = validation_context["repo_id"]
        async with sf() as session:
            report = await session.scalar(
                select(Report).where(Report.repository_id == repo_id)
            )
            assert report is None, "No report should be persisted"

    asyncio.run(_check())


@then("the response status is 422")
def then_status_422(validation_context: ValidationContext) -> None:
    """Assert the HTTP response is 422."""
    response = validation_context["response"]
    actual = int(response.status.split()[0])
    assert actual == 422, f"expected 422, got {actual}"


@then("the response body contains validation issues and a review reference")
def then_body_has_validation_detail(
    validation_context: ValidationContext,
) -> None:
    """Assert response body includes issues and review_id."""
    body = validation_context["response"].json
    assert "review_id" in body, "Missing review_id"
    assert "issues" in body, "Missing issues list"
    assert len(body["issues"]) >= 1, "Should have at least one issue"
