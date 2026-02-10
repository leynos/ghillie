"""Unit tests for the reporting Dramatiq actor."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import typing as typ

import pytest

from ghillie.bronze import RawEventWriter
from ghillie.silver import RawEventTransformer, Repository
from ghillie.status import MockStatusModel
from tests.helpers.event_builders import commit_envelope

if typ.TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclasses.dataclass(slots=True)
class RepositoryConfig:
    """Configuration for creating a test repository."""

    owner: str
    name: str
    estate_id: str
    ingestion_enabled: bool = True
    default_branch: str = "main"


async def _create_repository_with_estate(
    session_factory: async_sessionmaker[AsyncSession],
    config: RepositoryConfig,
) -> str:
    """Create a test repository and return its ID."""
    async with session_factory() as session, session.begin():
        repo = Repository(
            github_owner=config.owner,
            github_name=config.name,
            default_branch=config.default_branch,
            ingestion_enabled=config.ingestion_enabled,
            estate_id=config.estate_id,
        )
        session.add(repo)
        await session.flush()
        return repo.id


async def _get_repo_id(
    session_factory: async_sessionmaker[AsyncSession],
    owner: str,
    name: str,
) -> str:
    """Query repository by owner/name and return its ID."""
    from sqlalchemy import select

    async with session_factory() as session:
        repo = await session.scalar(
            select(Repository).where(
                Repository.github_owner == owner,
                Repository.github_name == name,
            )
        )
        assert repo is not None, f"Repository {owner}/{name} not found"
        return repo.id


@pytest.fixture
def estate_reporting_setup(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[ReportingService, RawEventWriter, RawEventTransformer]:
    """Provide common test dependencies for estate reporting tests.

    Returns
    -------
    tuple
        (ReportingService, RawEventWriter, RawEventTransformer) for test use.

    """
    from ghillie.evidence import EvidenceBundleService
    from ghillie.reporting.config import ReportingConfig
    from ghillie.reporting.service import (
        ReportingService,
        ReportingServiceDependencies,
    )

    deps = ReportingServiceDependencies(
        session_factory=session_factory,
        evidence_service=EvidenceBundleService(session_factory),
        status_model=MockStatusModel(),
    )
    service = ReportingService(deps, config=ReportingConfig())
    writer = RawEventWriter(session_factory)
    transformer = RawEventTransformer(session_factory)
    return service, writer, transformer


# Import ReportingService for type annotation in fixture return
if typ.TYPE_CHECKING:
    from ghillie.reporting.service import ReportingService

# Type alias for the estate reporting fixture return type
type EstateReportingSetup = tuple[ReportingService, RawEventWriter, RawEventTransformer]


class TestGenerateReportJob:
    """Tests for the generate_report_job Dramatiq actor."""

    @pytest.mark.asyncio
    async def test_generates_report_for_repository(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Actor generates a report for a repository with events."""
        from ghillie.evidence import EvidenceBundleService
        from ghillie.reporting.actor import _generate_report_async
        from ghillie.reporting.config import ReportingConfig
        from ghillie.reporting.service import (
            ReportingService,
            ReportingServiceDependencies,
        )

        repo_slug = "test/repo"
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)

        writer = RawEventWriter(session_factory)
        transformer = RawEventTransformer(session_factory)

        await writer.ingest(
            commit_envelope(repo_slug, "abc123", commit_time, "feat: feature")
        )
        await transformer.process_pending()

        repo_id = await _get_repo_id(session_factory, "test", "repo")

        # Create service with MockStatusModel for testing
        deps = ReportingServiceDependencies(
            session_factory=session_factory,
            evidence_service=EvidenceBundleService(session_factory),
            status_model=MockStatusModel(),
        )
        service = ReportingService(deps, config=ReportingConfig())

        result = await _generate_report_async(
            service=service,
            repository_id=repo_id,
            as_of=now,
        )

        assert result is not None, "Report should be generated"
        assert result.repository_id == repo_id, "Report should reference correct repo"

    @pytest.mark.asyncio
    async def test_skips_repository_with_no_events(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Actor returns None when no events exist in window."""
        from ghillie.evidence import EvidenceBundleService
        from ghillie.reporting.actor import _generate_report_async
        from ghillie.reporting.config import ReportingConfig
        from ghillie.reporting.service import (
            ReportingService,
            ReportingServiceDependencies,
        )

        repo_id = await _create_repository_with_estate(
            session_factory,
            RepositoryConfig(owner="empty", name="repo", estate_id="estate-1"),
        )
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)

        deps = ReportingServiceDependencies(
            session_factory=session_factory,
            evidence_service=EvidenceBundleService(session_factory),
            status_model=MockStatusModel(),
        )
        service = ReportingService(deps, config=ReportingConfig())

        result = await _generate_report_async(
            service=service,
            repository_id=repo_id,
            as_of=now,
        )

        assert result is None, "Should return None when no events in window"


class TestGenerateReportsForEstateJob:
    """Tests for the generate_reports_for_estate_job Dramatiq actor."""

    @pytest.mark.asyncio
    async def test_generates_reports_for_all_active_repositories(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        estate_reporting_setup: EstateReportingSetup,
    ) -> None:
        """Actor generates reports for all active repositories in estate."""
        from sqlalchemy import select

        from ghillie.reporting.actor import _generate_reports_for_estate_async

        service, writer, transformer = estate_reporting_setup

        estate_id = "estate-alpha"
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)

        # Create two repositories in the same estate
        await writer.ingest(
            commit_envelope("alpha/one", "sha1", commit_time, "feat: one")
        )
        await writer.ingest(
            commit_envelope("alpha/two", "sha2", commit_time, "fix: two")
        )
        await transformer.process_pending()

        # Set estate_id on both repos
        async with session_factory() as session, session.begin():
            repos = (await session.scalars(select(Repository))).all()
            for repo in repos:
                repo.estate_id = estate_id
                repo.ingestion_enabled = True

        results = await _generate_reports_for_estate_async(
            service=service,
            session_factory=session_factory,
            estate_id=estate_id,
            as_of=now,
        )

        assert len(results) == 2, "Should generate reports for both repositories"
        assert all(r is not None for r in results), "All reports should be non-None"

    @pytest.mark.asyncio
    async def test_skips_inactive_repositories(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        estate_reporting_setup: EstateReportingSetup,
    ) -> None:
        """Actor skips repositories with ingestion_enabled=False."""
        from sqlalchemy import select

        from ghillie.reporting.actor import _generate_reports_for_estate_async

        service, writer, transformer = estate_reporting_setup

        estate_id = "estate-beta"
        now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
        commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)

        await writer.ingest(
            commit_envelope("beta/active", "sha1", commit_time, "feat: active")
        )
        await writer.ingest(
            commit_envelope("beta/inactive", "sha2", commit_time, "fix: inactive")
        )
        await transformer.process_pending()

        async with session_factory() as session, session.begin():
            repos = (await session.scalars(select(Repository))).all()
            for repo in repos:
                repo.estate_id = estate_id
                if "inactive" in repo.github_name:
                    repo.ingestion_enabled = False
                else:
                    repo.ingestion_enabled = True

        results = await _generate_reports_for_estate_async(
            service=service,
            session_factory=session_factory,
            estate_id=estate_id,
            as_of=now,
        )

        # Only the active repository should have a report
        non_none_results = [r for r in results if r is not None]
        assert len(non_none_results) == 1, "Only active repo should have report"


@contextlib.contextmanager
def _build_service_caches(
    db_url: str,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> typ.Generator[None]:
    """Context manager that cleans up module-level engine and session caches.

    When *session_factory* is provided, pre-seeds the actor caches so that
    ``_build_service`` reuses the test database rather than creating a new
    in-memory one.
    """
    from ghillie.reporting.actor import _ENGINE_CACHE, _SESSION_FACTORY_CACHE

    if session_factory is not None:
        _SESSION_FACTORY_CACHE[db_url] = session_factory
        # The engine cache entry is not strictly needed when the session
        # factory is already cached, but we populate it to keep the two
        # caches consistent.
        _ENGINE_CACHE[db_url] = session_factory.kw["bind"]

    try:
        yield
    finally:
        _ENGINE_CACHE.pop(db_url, None)
        _SESSION_FACTORY_CACHE.pop(db_url, None)


# Synthetic URL used as the cache key in TestBuildServiceWiring tests.
# The value does not matter because the test pre-seeds the session cache.
_TEST_DB_URL = "sqlite+aiosqlite:///test-wiring"


class TestBuildServiceWiring:
    """Tests for _build_service actor-level wiring.

    Both tests exercise the service through its public API
    (``run_for_repository``) to verify that the sink wiring produces
    the expected filesystem effects rather than inspecting private
    attributes.
    """

    @pytest.mark.asyncio
    async def test_build_service_creates_sink_when_env_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
        session_factory: async_sessionmaker[AsyncSession],
        tmp_path: Path,
    ) -> None:
        """Sink writes Markdown files when GHILLIE_REPORT_SINK_PATH is set."""
        from ghillie.reporting.actor import _build_service

        sink_path = tmp_path / "reports"

        monkeypatch.setenv("GHILLIE_REPORT_SINK_PATH", str(sink_path))
        monkeypatch.setenv("GHILLIE_STATUS_MODEL_BACKEND", "mock")
        monkeypatch.delenv("GHILLIE_REPORTING_WINDOW_DAYS", raising=False)

        # Pre-seed actor caches with the test database session factory.
        with _build_service_caches(_TEST_DB_URL, session_factory=session_factory):
            service = _build_service(_TEST_DB_URL)

            # Set up a repository with events via ingestion.
            writer = RawEventWriter(session_factory)
            transformer = RawEventTransformer(session_factory)
            commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)
            await writer.ingest(
                commit_envelope(
                    "wiring/sink", "wire01", commit_time, "feat: wiring test"
                )
            )
            await transformer.process_pending()
            repo_id = await _get_repo_id(session_factory, "wiring", "sink")

            now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
            report = await service.run_for_repository(repo_id, as_of=now)

        assert report is not None, "Report should be generated"
        latest = sink_path / "wiring" / "sink" / "latest.md"
        assert latest.is_file(), "Sink should write latest.md when env var is set"

        content = latest.read_text()
        assert "wiring/sink" in content, (
            "Report content should include the repository slug"
        )

        # A dated archive file should also exist alongside latest.md.
        archive_files = [
            f
            for f in (sink_path / "wiring" / "sink").iterdir()
            if f.name != "latest.md" and f.suffix == ".md"
        ]
        assert len(archive_files) == 1, "Exactly one dated archive file should exist"

    @pytest.mark.asyncio
    async def test_build_service_no_sink_when_env_unset(
        self,
        monkeypatch: pytest.MonkeyPatch,
        session_factory: async_sessionmaker[AsyncSession],
        tmp_path: Path,
    ) -> None:
        """No Markdown files are written when GHILLIE_REPORT_SINK_PATH is unset."""
        from ghillie.reporting.actor import _build_service

        sink_path = tmp_path / "reports"

        monkeypatch.delenv("GHILLIE_REPORT_SINK_PATH", raising=False)
        monkeypatch.setenv("GHILLIE_STATUS_MODEL_BACKEND", "mock")
        monkeypatch.delenv("GHILLIE_REPORTING_WINDOW_DAYS", raising=False)

        # Pre-seed actor caches with the test database session factory.
        with _build_service_caches(_TEST_DB_URL, session_factory=session_factory):
            service = _build_service(_TEST_DB_URL)

            # Set up a repository with events via ingestion.
            writer = RawEventWriter(session_factory)
            transformer = RawEventTransformer(session_factory)
            commit_time = dt.datetime(2024, 7, 10, 10, 0, tzinfo=dt.UTC)
            await writer.ingest(
                commit_envelope(
                    "wiring/nosink", "wire02", commit_time, "feat: no-sink test"
                )
            )
            await transformer.process_pending()
            repo_id = await _get_repo_id(session_factory, "wiring", "nosink")

            now = dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
            report = await service.run_for_repository(repo_id, as_of=now)

        assert report is not None, "Report should still be generated without a sink"
        assert not sink_path.exists(), (
            "No report directory should be created when sink env var is unset"
        )
