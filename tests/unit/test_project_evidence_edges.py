"""Unit tests for project evidence dependency edges.

Verifies that ``ProjectEvidenceBundleService.build_bundle`` includes
correct intra-project dependency edges (``depends_on``,
``emits_events_to``) and excludes cross-project ``blocked_by`` edges.

Examples
--------
Run these tests::

    pytest tests/unit/test_project_evidence_edges.py -q

"""

from __future__ import annotations

import typing as typ

import pytest

from tests.unit.helpers.project_evidence_helpers import build_wildside_bundle

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.evidence.project_service import ProjectEvidenceBundleService


@pytest.mark.usefixtures("_import_wildside")
class TestProjectEvidenceEdges:
    """Tests for dependency edges in the project evidence bundle."""

    def test_bundle_contains_dependency_edges(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes dependency edges from the component graph."""
        bundle = build_wildside_bundle(project_evidence_service, session_factory)

        assert len(bundle.dependencies) > 0, "expected at least one dependency edge"
        # wildside-core depends_on wildside-engine
        core_to_engine = [
            d
            for d in bundle.dependencies
            if d.from_component == "wildside-core"
            and d.to_component == "wildside-engine"
            and d.relationship == "depends_on"
        ]
        assert len(core_to_engine) == 1, (
            "expected one wildside-core depends_on wildside-engine edge"
        )
        assert core_to_engine[0].kind == "runtime", (
            f"expected kind 'runtime', got {core_to_engine[0].kind!r}"
        )

    def test_cross_project_blocked_by_edges_excluded(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Cross-project blocked_by edges are excluded from the bundle.

        wildside-engine is blocked_by ortho-config, but ortho-config
        belongs to df12-foundations. This edge should not appear in the
        Wildside project bundle.
        """
        bundle = build_wildside_bundle(project_evidence_service, session_factory)

        blocked = bundle.blocked_dependencies
        # ortho-config is in df12-foundations, not wildside, so the
        # blocked_by edge is cross-project and excluded.
        engine_blocked = [
            d
            for d in blocked
            if d.from_component == "wildside-engine"
            and d.to_component == "ortho-config"
        ]
        assert len(engine_blocked) == 0, (
            "cross-project blocked_by edges should be excluded"
        )

    def test_bundle_contains_emits_events_to_edges(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Bundle includes emits_events_to edges."""
        bundle = build_wildside_bundle(project_evidence_service, session_factory)

        emits = [d for d in bundle.dependencies if d.relationship == "emits_events_to"]
        assert len(emits) >= 1, "expected at least one emits_events_to edge"
        # wildside-core emits_events_to wildside-mockup
        core_to_mockup = [
            d
            for d in emits
            if d.from_component == "wildside-core"
            and d.to_component == "wildside-mockup"
        ]
        assert len(core_to_mockup) == 1, (
            "expected one wildside-core emits_events_to wildside-mockup edge"
        )
