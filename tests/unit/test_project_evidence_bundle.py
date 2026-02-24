"""Unit tests for project evidence bundle structure and components.

Verifies that ``ProjectEvidenceBundleService.build_bundle`` produces
bundles with correct project metadata, component inventory, lifecycle
stages, repository slugs, ``generated_at`` timestamps, and component
types.  Repository-summary and dependency-edge assertions are covered
by sibling modules.

Examples
--------
Run these tests::

    pytest tests/unit/test_project_evidence_bundle.py -q

"""

from __future__ import annotations

import asyncio
import typing as typ

import pytest

from tests.unit.project_evidence_helpers import build_wildside_bundle, get_estate_id

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.evidence.project_service import ProjectEvidenceBundleService


@pytest.mark.usefixtures("_import_wildside")
class TestProjectEvidenceBundleStructure:
    """Tests for bundle structure, metadata, components, and lifecycle."""

    def test_project_not_found_raises_value_error(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Requesting a nonexistent project raises ValueError."""
        eid = get_estate_id(session_factory)

        with pytest.raises(ValueError, match="not found"):
            asyncio.run(project_evidence_service.build_bundle("nonexistent", eid))

    def test_bundle_contains_project_metadata(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle project metadata matches catalogue data."""
        bundle = build_wildside_bundle(project_evidence_service, session_factory)

        assert bundle.project.key == "wildside", "project key mismatch"
        assert bundle.project.name == "Wildside", "project name mismatch"
        assert bundle.project.programme == "df12", "programme mismatch"
        assert bundle.project.description is not None, "description missing"

    def test_bundle_contains_all_components(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes all components from the catalogue."""
        bundle = build_wildside_bundle(project_evidence_service, session_factory)

        assert bundle.component_count == 4, (
            f"expected 4 components, got {bundle.component_count}"
        )
        keys = {c.key for c in bundle.components}
        assert keys == {
            "wildside-core",
            "wildside-engine",
            "wildside-mockup",
            "wildside-ingestion",
        }, f"unexpected component keys: {keys}"

    def test_bundle_lifecycle_stages(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Components reflect their catalogue lifecycle stages."""
        bundle = build_wildside_bundle(project_evidence_service, session_factory)

        assert len(bundle.active_components) == 3, (
            f"expected 3 active components, got {len(bundle.active_components)}"
        )
        assert len(bundle.planned_components) == 1, (
            f"expected 1 planned component, got {len(bundle.planned_components)}"
        )
        assert bundle.planned_components[0].key == "wildside-ingestion", (
            f"expected wildside-ingestion, got {bundle.planned_components[0].key}"
        )

    def test_planned_component_has_no_repository(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Planned components without repos have no repository_slug."""
        bundle = build_wildside_bundle(project_evidence_service, session_factory)

        ingestion = next(c for c in bundle.components if c.key == "wildside-ingestion")
        assert ingestion.has_repository is False, (
            "wildside-ingestion should lack a repository"
        )
        assert ingestion.repository_summary is None, (
            "wildside-ingestion should have no summary"
        )
        assert ingestion.lifecycle == "planned", (
            f"expected lifecycle 'planned', got {ingestion.lifecycle!r}"
        )

    def test_active_component_has_repository_slug(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Active components with repos have repository_slug populated."""
        bundle = build_wildside_bundle(project_evidence_service, session_factory)

        core = next(c for c in bundle.components if c.key == "wildside-core")
        assert core.has_repository is True, "wildside-core should have a repository"
        assert core.repository_slug == "leynos/wildside", (
            f"expected leynos/wildside, got {core.repository_slug!r}"
        )

    def test_bundle_generated_at_is_set(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle has a generated_at timestamp."""
        bundle = build_wildside_bundle(project_evidence_service, session_factory)

        assert bundle.generated_at is not None, (
            "bundle should have a generated_at timestamp"
        )

    def test_component_type_is_captured(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Component type from catalogue is included in evidence."""
        bundle = build_wildside_bundle(project_evidence_service, session_factory)

        core = next(c for c in bundle.components if c.key == "wildside-core")
        assert core.component_type == "service", (
            f"expected component_type 'service', got {core.component_type!r}"
        )

        ingestion = next(c for c in bundle.components if c.key == "wildside-ingestion")
        assert ingestion.component_type == "data-pipeline", (
            f"expected component_type 'data-pipeline', got {ingestion.component_type!r}"
        )
