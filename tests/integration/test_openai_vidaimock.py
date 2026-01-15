"""Integration tests for OpenAI status model with VidaiMock."""

from __future__ import annotations

import datetime as dt
import typing as typ

import pytest

from ghillie.evidence.models import (
    CommitEvidence,
    PullRequestEvidence,
    ReportStatus,
    RepositoryEvidenceBundle,
    RepositoryMetadata,
    WorkType,
    WorkTypeGrouping,
)
from ghillie.status.openai_client import OpenAIStatusModel

if typ.TYPE_CHECKING:
    from ghillie.status.config import OpenAIStatusModelConfig


@pytest.fixture
def repository_metadata() -> RepositoryMetadata:
    """Provide basic repository metadata for integration tests."""
    return RepositoryMetadata(
        id="repo-integration-123",
        owner="octo",
        name="reef",
        default_branch="main",
        estate_id="wildside",
    )


@pytest.fixture
def feature_evidence(
    repository_metadata: RepositoryMetadata,
) -> RepositoryEvidenceBundle:
    """Provide evidence bundle with feature activity for integration tests."""
    return RepositoryEvidenceBundle(
        repository=repository_metadata,
        window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
        commits=(
            CommitEvidence(
                sha="abc123",
                message="feat: add new dashboard",
                author_name="Alice",
                committed_at=dt.datetime(2024, 7, 2, tzinfo=dt.UTC),
                work_type=WorkType.FEATURE,
            ),
        ),
        pull_requests=(
            PullRequestEvidence(
                id=101,
                number=42,
                title="Add new dashboard feature",
                author_login="alice",
                state="merged",
                labels=("feature", "enhancement"),
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
                sample_titles=("Add new dashboard feature",),
            ),
        ),
        event_fact_ids=(1, 2),
        generated_at=dt.datetime(2024, 7, 8, 0, 0, 1, tzinfo=dt.UTC),
    )


@pytest.mark.integration
class TestOpenAIStatusModelWithVidaiMock:
    """Integration tests using VidaiMock as the LLM backend."""

    @pytest.mark.asyncio
    async def test_round_trip_inference(
        self,
        openai_config_for_vidaimock: OpenAIStatusModelConfig,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Test complete request/response flow with VidaiMock."""
        model = OpenAIStatusModel(openai_config_for_vidaimock)
        try:
            result = await model.summarize_repository(feature_evidence)

            # Verify structured result
            assert result.summary is not None
            assert len(result.summary) > 0
            assert result.status in (
                ReportStatus.ON_TRACK,
                ReportStatus.AT_RISK,
                ReportStatus.BLOCKED,
                ReportStatus.UNKNOWN,
            )
        finally:
            await model.aclose()

    @pytest.mark.asyncio
    async def test_result_contains_expected_fields(
        self,
        openai_config_for_vidaimock: OpenAIStatusModelConfig,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Test that result contains all expected fields from VidaiMock response."""
        model = OpenAIStatusModel(openai_config_for_vidaimock)
        try:
            result = await model.summarize_repository(feature_evidence)

            # VidaiMock is configured to return on_track status
            assert result.status == ReportStatus.ON_TRACK

            # Should have highlights (VidaiMock returns 2)
            assert len(result.highlights) >= 1

            # Should have next_steps (VidaiMock returns 2)
            assert len(result.next_steps) >= 1

            # Summary should mention the repository
            assert "octo/reef" in result.summary or "reef" in result.summary
        finally:
            await model.aclose()

    @pytest.mark.asyncio
    async def test_implements_status_model_protocol(
        self,
        openai_config_for_vidaimock: OpenAIStatusModelConfig,
    ) -> None:
        """Test that OpenAIStatusModel implements StatusModel protocol."""
        from ghillie.status.protocol import StatusModel

        model = OpenAIStatusModel(openai_config_for_vidaimock)
        try:
            assert isinstance(model, StatusModel)
        finally:
            await model.aclose()

    @pytest.mark.asyncio
    async def test_client_uses_configured_endpoint(
        self,
        vidaimock_server: str,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Test that client uses the configured endpoint."""
        from ghillie.status.config import OpenAIStatusModelConfig

        config = OpenAIStatusModelConfig(
            api_key="test-key",
            endpoint=f"{vidaimock_server}/v1/chat/completions",
        )
        model = OpenAIStatusModel(config)
        try:
            # This should succeed because we're using the VidaiMock endpoint
            result = await model.summarize_repository(feature_evidence)
            assert result.summary is not None
        finally:
            await model.aclose()

    @pytest.mark.asyncio
    async def test_client_handles_response_correctly(
        self,
        openai_config_for_vidaimock: OpenAIStatusModelConfig,
        feature_evidence: RepositoryEvidenceBundle,
    ) -> None:
        """Test that client correctly parses VidaiMock response."""
        model = OpenAIStatusModel(openai_config_for_vidaimock)
        try:
            result = await model.summarize_repository(feature_evidence)

            # Result should be a proper RepositoryStatusResult
            from ghillie.status.models import RepositoryStatusResult

            assert isinstance(result, RepositoryStatusResult)

            # Should have tuple fields (not lists)
            assert isinstance(result.highlights, tuple)
            assert isinstance(result.risks, tuple)
            assert isinstance(result.next_steps, tuple)
        finally:
            await model.aclose()
