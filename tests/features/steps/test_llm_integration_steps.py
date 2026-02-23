"""Step definitions for LLM integration feature tests."""

from __future__ import annotations

import asyncio
import datetime as dt
import typing as typ
from http import HTTPStatus

import httpx
import pytest
from pytest_bdd import given, scenarios, then, when

from ghillie.evidence.models import (
    CommitEvidence,
    PullRequestEvidence,
    ReportStatus,
    RepositoryEvidenceBundle,
    RepositoryMetadata,
    WorkType,
    WorkTypeGrouping,
)
from ghillie.status.errors import OpenAIAPIError, OpenAIResponseShapeError

if typ.TYPE_CHECKING:
    from ghillie.status.models import RepositoryStatusResult

# Register scenarios from the feature file
scenarios("../llm_integration.feature")


class LLMIntegrationContext(typ.TypedDict, total=False):
    """Context shared between BDD steps."""

    evidence: RepositoryEvidenceBundle
    result: RepositoryStatusResult
    error: Exception | None
    timeout_enabled: bool
    invalid_json_enabled: bool


@pytest.fixture
def llm_context() -> LLMIntegrationContext:
    """Provide shared context for LLM integration steps."""
    return LLMIntegrationContext()


@given("a repository with evidence bundle")
def given_repository_with_evidence(llm_context: LLMIntegrationContext) -> None:
    """Set up evidence bundle for testing."""
    repository = RepositoryMetadata(
        id="repo-bdd-123",
        owner="octo",
        name="reef",
        default_branch="main",
        estate_id="wildside",
    )
    llm_context["evidence"] = RepositoryEvidenceBundle(
        repository=repository,
        window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        commits=(
            CommitEvidence(
                sha="abc123",
                message="feat: add new feature",
                author_name="Alice",
                committed_at=dt.datetime(2024, 7, 2, tzinfo=dt.UTC),
                work_type=WorkType.FEATURE,
            ),
        ),
        pull_requests=(
            PullRequestEvidence(
                id=101,
                number=42,
                title="Add new feature",
                author_login="alice",
                state="merged",
                labels=("feature",),
                created_at=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                merged_at=dt.datetime(2024, 7, 2, tzinfo=dt.UTC),
                work_type=WorkType.FEATURE,
            ),
        ),
        work_type_groupings=(
            WorkTypeGrouping(
                work_type=WorkType.FEATURE,
                commit_count=1,
                pr_count=1,
                issue_count=0,
                sample_titles=("Add new feature",),
            ),
        ),
        event_fact_ids=(1, 2),
        generated_at=dt.datetime(2024, 7, 8, 0, 0, 1, tzinfo=dt.UTC),
    )


@given("the LLM service is available")
def given_llm_service_available(llm_context: LLMIntegrationContext) -> None:
    """Mark LLM service as available (normal operation)."""
    llm_context["timeout_enabled"] = False
    llm_context["invalid_json_enabled"] = False


@given("the LLM service is configured to timeout")
def given_llm_service_timeout(llm_context: LLMIntegrationContext) -> None:
    """Configure LLM service to simulate timeout."""
    llm_context["timeout_enabled"] = True


@given("the LLM service returns invalid JSON")
def given_llm_service_invalid_json(llm_context: LLMIntegrationContext) -> None:
    """Configure LLM service to return invalid JSON."""
    llm_context["invalid_json_enabled"] = True


def _create_timeout_transport() -> httpx.AsyncBaseTransport:
    """Create a mock transport that raises TimeoutException."""

    class TimeoutTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(
            self, request: httpx.Request
        ) -> httpx.Response:  # pragma: no cover
            msg = "Mock timeout"
            raise httpx.TimeoutException(msg, request=request)

    return TimeoutTransport()


def _create_invalid_json_transport() -> httpx.AsyncBaseTransport:
    """Create a mock transport that returns invalid JSON."""

    class InvalidJSONTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=HTTPStatus.OK,
                json={
                    "id": "chatcmpl-test",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "not valid json {",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                },
            )

    return InvalidJSONTransport()


@when("I request a status report using the OpenAI model")
def when_request_status_report(
    llm_context: LLMIntegrationContext,
    vidaimock_server: str,
) -> None:
    """Request status report from OpenAI model."""
    from ghillie.status.config import OpenAIStatusModelConfig
    from ghillie.status.openai_client import OpenAIStatusModel

    async def _request_report() -> None:
        evidence = llm_context["evidence"]

        config = OpenAIStatusModelConfig(
            api_key="test-key",
            endpoint=f"{vidaimock_server}/v1/chat/completions",
        )

        http_client: httpx.AsyncClient | None = None
        model: OpenAIStatusModel | None = None
        try:
            if llm_context.get("timeout_enabled"):
                http_client = httpx.AsyncClient(transport=_create_timeout_transport())
            elif llm_context.get("invalid_json_enabled"):
                http_client = httpx.AsyncClient(
                    transport=_create_invalid_json_transport()
                )

            model = OpenAIStatusModel(config, http_client=http_client)
            result = await model.summarize_repository(evidence)
            llm_context["result"] = result
        except (OpenAIAPIError, OpenAIResponseShapeError) as e:
            llm_context["error"] = e
        finally:
            if model is not None:
                await model.aclose()
            if http_client is not None:
                await http_client.aclose()

    asyncio.run(_request_report())


@then("I receive a structured status result")
def then_receive_structured_result(llm_context: LLMIntegrationContext) -> None:
    """Verify structured result was received."""
    error = llm_context.get("error")
    assert error is None, f"Expected no error but got: {error}"
    result = llm_context.get("result")
    assert result is not None, "Expected a result but got None"


@then("the result contains a summary mentioning the repository")
def then_result_contains_summary(llm_context: LLMIntegrationContext) -> None:
    """Verify result summary mentions repository."""
    result = llm_context["result"]
    assert result.summary is not None, "Expected summary to be present but was None"
    assert len(result.summary) > 0, "Expected non-empty summary"
    # VidaiMock is configured to return summary mentioning octo/reef
    assert "octo/reef" in result.summary or "reef" in result.summary.lower(), (
        f"Expected summary to mention repository, got: {result.summary}"
    )


@then("the result contains a valid status code")
def then_result_contains_valid_status(llm_context: LLMIntegrationContext) -> None:
    """Verify result has valid status code."""
    result = llm_context["result"]
    valid_statuses = (
        ReportStatus.ON_TRACK,
        ReportStatus.AT_RISK,
        ReportStatus.BLOCKED,
        ReportStatus.UNKNOWN,
    )
    assert result.status in valid_statuses, (
        f"Expected status in {valid_statuses}, got: {result.status}"
    )


@then("an API timeout error is raised")
def then_api_timeout_error(llm_context: LLMIntegrationContext) -> None:
    """Verify API timeout error was raised."""
    error = llm_context.get("error")
    assert error is not None, "Expected an error but none was raised"
    assert isinstance(error, OpenAIAPIError), (
        f"Expected OpenAIAPIError but got {type(error).__name__}: {error}"
    )


@then("the error message indicates a timeout occurred")
def then_error_indicates_timeout(llm_context: LLMIntegrationContext) -> None:
    """Verify error message mentions timeout."""
    error = llm_context.get("error")
    assert error is not None, "Expected an error but none was raised"
    assert "timeout" in str(error).lower(), (
        f"Expected error message to mention 'timeout', got: {error}"
    )


@then("a response shape error is raised")
def then_response_shape_error(llm_context: LLMIntegrationContext) -> None:
    """Verify response shape error was raised."""
    error = llm_context.get("error")
    assert error is not None, "Expected an error but none was raised"
    assert isinstance(error, OpenAIResponseShapeError), (
        f"Expected OpenAIResponseShapeError but got {type(error).__name__}: {error}"
    )


@then("the error message indicates invalid JSON")
def then_error_indicates_invalid_json(llm_context: LLMIntegrationContext) -> None:
    """Verify error message mentions JSON."""
    error = llm_context.get("error")
    assert error is not None, "Expected an error but none was raised"
    error_str = str(error).lower()
    assert "json" in error_str or "parse" in error_str, (
        f"Expected error message to mention 'json' or 'parse', got: {error}"
    )
