"""Unit tests for project evidence bundle model structures."""

# ruff: noqa: D102

from __future__ import annotations

import datetime as dt

import msgspec
import pytest

from ghillie.evidence import (
    ReportStatus,
)
from ghillie.evidence.models import (
    ComponentDependencyEvidence,
    ComponentEvidence,
    ComponentRepositorySummary,
    ProjectEvidenceBundle,
    ProjectMetadata,
)

# -- Parametrised cross-model tests ------------------------------------------


@pytest.mark.parametrize(
    ("model_factory", "field_to_modify", "new_value"),
    [
        pytest.param(
            lambda: ProjectMetadata(key="test", name="Test"),
            "key",
            "modified",
            id="ProjectMetadata",
        ),
        pytest.param(
            lambda: ComponentRepositorySummary(
                repository_slug="leynos/wildside",
                report_id="rpt-001",
                window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                status=ReportStatus.ON_TRACK,
                summary="Summary.",
            ),
            "status",
            ReportStatus.BLOCKED,
            id="ComponentRepositorySummary",
        ),
        pytest.param(
            lambda: ComponentEvidence(
                key="wildside-core",
                name="Wildside Core Service",
                component_type="service",
                lifecycle="active",
            ),
            "key",
            "other",
            id="ComponentEvidence",
        ),
        pytest.param(
            lambda: ComponentDependencyEvidence(
                from_component="wildside-core",
                to_component="wildside-engine",
                relationship="depends_on",
                kind="runtime",
            ),
            "kind",
            "dev",
            id="ComponentDependencyEvidence",
        ),
        pytest.param(
            lambda: ProjectEvidenceBundle(
                project=ProjectMetadata(key="test", name="Test"),
                components=(),
                dependencies=(),
            ),
            "components",
            (),
            id="ProjectEvidenceBundle",
        ),
    ],
)
def test_frozen_immutability_for_all_models(
    model_factory: object,
    field_to_modify: str,
    new_value: object,
) -> None:
    """Verify all evidence models are frozen msgspec structs."""
    instance = model_factory()  # type: ignore[operator]
    with pytest.raises(AttributeError):
        setattr(instance, field_to_modify, new_value)


def _check_project_metadata_roundtrip(decoded: object) -> None:
    assert decoded.key == "wildside"  # type: ignore[union-attr]
    assert decoded.name == "Wildside"  # type: ignore[union-attr]
    assert decoded.programme == "df12"  # type: ignore[union-attr]
    assert decoded.documentation_paths == ("docs/roadmap.md",)  # type: ignore[union-attr]


def _check_component_repo_summary_roundtrip(decoded: object) -> None:
    assert decoded.repository_slug == "leynos/wildside"  # type: ignore[union-attr]
    assert decoded.status == ReportStatus.ON_TRACK  # type: ignore[union-attr]
    assert decoded.highlights == ("Feature A shipped",)  # type: ignore[union-attr]


def _check_component_evidence_roundtrip(decoded: object) -> None:
    assert decoded.key == "wildside-core"  # type: ignore[union-attr]
    assert decoded.has_repository is True  # type: ignore[union-attr]
    assert decoded.notes == ("Primary service",)  # type: ignore[union-attr]


def _check_dependency_evidence_roundtrip(decoded: object) -> None:
    assert decoded.from_component == "wildside-core"  # type: ignore[union-attr]
    assert decoded.relationship == "blocked_by"  # type: ignore[union-attr]
    assert decoded.rationale == "Config releases needed."  # type: ignore[union-attr]


def _check_bundle_roundtrip(decoded: object) -> None:
    assert decoded.project.key == "wildside"  # type: ignore[union-attr]
    assert decoded.component_count == 2  # type: ignore[union-attr]
    assert len(decoded.dependencies) == 1  # type: ignore[union-attr]
    assert decoded.components[0].has_repository is True  # type: ignore[union-attr]
    assert decoded.components[1].has_repository is False  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("model_factory", "model_type", "verify"),
    [
        pytest.param(
            lambda: ProjectMetadata(
                key="wildside",
                name="Wildside",
                description="Streaming platform.",
                programme="df12",
                documentation_paths=("docs/roadmap.md",),
            ),
            ProjectMetadata,
            _check_project_metadata_roundtrip,
            id="ProjectMetadata",
        ),
        pytest.param(
            lambda: ComponentRepositorySummary(
                repository_slug="leynos/wildside",
                report_id="rpt-001",
                window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                status=ReportStatus.ON_TRACK,
                summary="All good.",
                highlights=("Feature A shipped",),
            ),
            ComponentRepositorySummary,
            _check_component_repo_summary_roundtrip,
            id="ComponentRepositorySummary",
        ),
        pytest.param(
            lambda: ComponentEvidence(
                key="wildside-core",
                name="Wildside Core Service",
                component_type="service",
                lifecycle="active",
                repository_slug="leynos/wildside",
                notes=("Primary service",),
            ),
            ComponentEvidence,
            _check_component_evidence_roundtrip,
            id="ComponentEvidence",
        ),
        pytest.param(
            lambda: ComponentDependencyEvidence(
                from_component="wildside-core",
                to_component="ortho-config",
                relationship="blocked_by",
                kind="runtime",
                rationale="Config releases needed.",
            ),
            ComponentDependencyEvidence,
            _check_dependency_evidence_roundtrip,
            id="ComponentDependencyEvidence",
        ),
        pytest.param(
            lambda: ProjectEvidenceBundle(
                project=ProjectMetadata(key="wildside", name="Wildside"),
                components=(
                    ComponentEvidence(
                        key="wildside-core",
                        name="Wildside Core Service",
                        component_type="service",
                        lifecycle="active",
                        repository_slug="leynos/wildside",
                    ),
                    ComponentEvidence(
                        key="wildside-ingestion",
                        name="Wildside Ingestion Pipeline",
                        component_type="data-pipeline",
                        lifecycle="planned",
                    ),
                ),
                dependencies=(
                    ComponentDependencyEvidence(
                        from_component="wildside-core",
                        to_component="wildside-engine",
                        relationship="depends_on",
                        kind="runtime",
                    ),
                ),
                generated_at=dt.datetime(2024, 7, 8, 12, 0, tzinfo=dt.UTC),
            ),
            ProjectEvidenceBundle,
            _check_bundle_roundtrip,
            id="ProjectEvidenceBundle",
        ),
    ],
)
def test_msgspec_encoding_roundtrip_for_all_models(
    model_factory: object,
    model_type: type,
    verify: object,
) -> None:
    """Verify msgspec encode/decode roundtrip for all evidence models."""
    instance = model_factory()  # type: ignore[operator]
    encoded = msgspec.json.encode(instance)
    decoded = msgspec.json.decode(encoded, type=model_type)
    verify(decoded)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("model_factory", "field_assertions"),
    [
        pytest.param(
            lambda: ProjectMetadata(key="wildside", name="Wildside"),
            {"key": "wildside", "name": "Wildside"},
            id="ProjectMetadata",
        ),
        pytest.param(
            lambda: ComponentRepositorySummary(
                repository_slug="leynos/wildside",
                report_id="rpt-001",
                window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                status=ReportStatus.ON_TRACK,
                summary="Good progress this week.",
            ),
            {
                "repository_slug": "leynos/wildside",
                "report_id": "rpt-001",
                "status": ReportStatus.ON_TRACK,
                "summary": "Good progress this week.",
            },
            id="ComponentRepositorySummary",
        ),
        pytest.param(
            lambda: ComponentEvidence(
                key="wildside-core",
                name="Wildside Core Service",
                component_type="service",
                lifecycle="active",
            ),
            {
                "key": "wildside-core",
                "name": "Wildside Core Service",
                "component_type": "service",
                "lifecycle": "active",
            },
            id="ComponentEvidence",
        ),
        pytest.param(
            lambda: ComponentDependencyEvidence(
                from_component="wildside-core",
                to_component="wildside-engine",
                relationship="depends_on",
                kind="runtime",
            ),
            {
                "from_component": "wildside-core",
                "to_component": "wildside-engine",
                "relationship": "depends_on",
                "kind": "runtime",
            },
            id="ComponentDependencyEvidence",
        ),
    ],
)
def test_required_fields_for_all_models(
    model_factory: object,
    field_assertions: dict[str, object],
) -> None:
    """Verify required fields are set correctly for all evidence models."""
    instance = model_factory()  # type: ignore[operator]
    for field_name, expected in field_assertions.items():
        assert getattr(instance, field_name) == expected


@pytest.mark.parametrize(
    ("model_factory", "default_assertions"),
    [
        pytest.param(
            lambda: ProjectMetadata(key="wildside", name="Wildside"),
            {"description": None, "programme": None, "documentation_paths": ()},
            id="ProjectMetadata",
        ),
        pytest.param(
            lambda: ComponentRepositorySummary(
                repository_slug="leynos/wildside",
                report_id="rpt-001",
                window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                status=ReportStatus.ON_TRACK,
                summary="Summary text.",
            ),
            {
                "highlights": (),
                "risks": (),
                "next_steps": (),
                "generated_at": None,
            },
            id="ComponentRepositorySummary",
        ),
        pytest.param(
            lambda: ComponentEvidence(
                key="wildside-core",
                name="Wildside Core Service",
                component_type="service",
                lifecycle="active",
            ),
            {
                "description": None,
                "repository_slug": None,
                "repository_summary": None,
                "notes": (),
            },
            id="ComponentEvidence",
        ),
        pytest.param(
            lambda: ComponentDependencyEvidence(
                from_component="wildside-core",
                to_component="wildside-engine",
                relationship="depends_on",
                kind="runtime",
            ),
            {"rationale": None},
            id="ComponentDependencyEvidence",
        ),
    ],
)
def test_default_values_for_all_models(
    model_factory: object,
    default_assertions: dict[str, object],
) -> None:
    """Verify default field values for all evidence models."""
    instance = model_factory()  # type: ignore[operator]
    for field_name, expected in default_assertions.items():
        assert getattr(instance, field_name) == expected


class TestProjectMetadata:
    """Tests for ProjectMetadata struct."""

    def test_full_construction(self) -> None:
        metadata = ProjectMetadata(
            key="wildside",
            name="Wildside",
            description="Transactional streaming platform.",
            programme="df12",
            documentation_paths=("docs/roadmap.md", "docs/adr/"),
        )

        assert metadata.description == "Transactional streaming platform."
        assert metadata.programme == "df12"
        assert metadata.documentation_paths == ("docs/roadmap.md", "docs/adr/")


class TestComponentRepositorySummary:
    """Tests for ComponentRepositorySummary struct."""

    def test_full_construction(self) -> None:
        generated = dt.datetime(2024, 7, 8, 12, 0, tzinfo=dt.UTC)
        summary = ComponentRepositorySummary(
            repository_slug="leynos/wildside",
            report_id="rpt-001",
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            status=ReportStatus.AT_RISK,
            summary="Some concerns.",
            highlights=("Shipped v2.0",),
            risks=("Tech debt",),
            next_steps=("Refactor module X",),
            generated_at=generated,
        )

        assert summary.status == ReportStatus.AT_RISK
        assert summary.highlights == ("Shipped v2.0",)
        assert summary.risks == ("Tech debt",)
        assert summary.next_steps == ("Refactor module X",)
        assert summary.generated_at == generated


class TestComponentEvidence:
    """Tests for ComponentEvidence struct."""

    def test_has_repository_true(self) -> None:
        component = ComponentEvidence(
            key="wildside-core",
            name="Wildside Core Service",
            component_type="service",
            lifecycle="active",
            repository_slug="leynos/wildside",
        )

        assert component.has_repository is True

    def test_has_repository_false(self) -> None:
        component = ComponentEvidence(
            key="wildside-ingestion",
            name="Wildside Ingestion Pipeline",
            component_type="data-pipeline",
            lifecycle="planned",
        )

        assert component.has_repository is False

    def test_full_construction_with_summary(self) -> None:
        summary = ComponentRepositorySummary(
            repository_slug="leynos/wildside",
            report_id="rpt-001",
            window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
            window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
            status=ReportStatus.ON_TRACK,
            summary="On track.",
        )
        component = ComponentEvidence(
            key="wildside-core",
            name="Wildside Core Service",
            component_type="service",
            lifecycle="active",
            description="User-facing API.",
            repository_slug="leynos/wildside",
            repository_summary=summary,
            notes=("Primary service",),
        )

        assert component.repository_summary is not None
        assert component.repository_summary.status == ReportStatus.ON_TRACK
        assert component.notes == ("Primary service",)


class TestComponentDependencyEvidence:
    """Tests for ComponentDependencyEvidence struct."""

    def test_full_construction(self) -> None:
        dep = ComponentDependencyEvidence(
            from_component="wildside-core",
            to_component="ortho-config",
            relationship="blocked_by",
            kind="runtime",
            rationale="Requires config releases for rollout.",
        )

        assert dep.relationship == "blocked_by"
        assert dep.rationale == "Requires config releases for rollout."


class TestProjectEvidenceBundle:
    """Tests for ProjectEvidenceBundle struct."""

    @pytest.fixture
    def sample_project(self) -> ProjectMetadata:
        return ProjectMetadata(key="wildside", name="Wildside")

    @pytest.fixture
    def active_component(self) -> ComponentEvidence:
        return ComponentEvidence(
            key="wildside-core",
            name="Wildside Core Service",
            component_type="service",
            lifecycle="active",
            repository_slug="leynos/wildside",
            repository_summary=ComponentRepositorySummary(
                repository_slug="leynos/wildside",
                report_id="rpt-001",
                window_start=dt.datetime(2024, 7, 1, tzinfo=dt.UTC),
                window_end=dt.datetime(2024, 7, 8, tzinfo=dt.UTC),
                status=ReportStatus.ON_TRACK,
                summary="On track.",
            ),
        )

    @pytest.fixture
    def planned_component(self) -> ComponentEvidence:
        return ComponentEvidence(
            key="wildside-ingestion",
            name="Wildside Ingestion Pipeline",
            component_type="data-pipeline",
            lifecycle="planned",
        )

    @pytest.fixture
    def deprecated_component(self) -> ComponentEvidence:
        return ComponentEvidence(
            key="wildside-legacy",
            name="Wildside Legacy",
            component_type="service",
            lifecycle="deprecated",
            repository_slug="leynos/wildside-legacy",
        )

    def _create_bundle(
        self,
        project: ProjectMetadata,
        components: tuple[ComponentEvidence, ...],
        dependencies: tuple[ComponentDependencyEvidence, ...] = (),
    ) -> ProjectEvidenceBundle:
        """Create a ProjectEvidenceBundle with the given project and components.

        Parameters
        ----------
        project
            Project metadata for the bundle.
        components
            Tuple of component evidence items.
        dependencies
            Tuple of dependency edges (defaults to empty).

        Returns
        -------
        ProjectEvidenceBundle
            The constructed bundle.

        """
        return ProjectEvidenceBundle(
            project=project,
            components=components,
            dependencies=dependencies,
        )

    def test_minimal_construction(self, sample_project: ProjectMetadata) -> None:
        bundle = ProjectEvidenceBundle(
            project=sample_project,
            components=(),
            dependencies=(),
        )

        assert bundle.project.key == "wildside"
        assert bundle.components == ()
        assert bundle.dependencies == ()

    def test_default_values(self, sample_project: ProjectMetadata) -> None:
        bundle = ProjectEvidenceBundle(
            project=sample_project,
            components=(),
            dependencies=(),
        )

        assert bundle.previous_reports == ()
        assert bundle.generated_at is None

    def test_component_count(
        self,
        sample_project: ProjectMetadata,
        active_component: ComponentEvidence,
        planned_component: ComponentEvidence,
    ) -> None:
        bundle = self._create_bundle(
            sample_project,
            components=(active_component, planned_component),
        )

        assert bundle.component_count == 2

    def test_active_components(
        self,
        sample_project: ProjectMetadata,
        active_component: ComponentEvidence,
        planned_component: ComponentEvidence,
        deprecated_component: ComponentEvidence,
    ) -> None:
        bundle = self._create_bundle(
            sample_project,
            components=(
                active_component,
                planned_component,
                deprecated_component,
            ),
        )

        active = bundle.active_components
        assert len(active) == 1
        assert active[0].key == "wildside-core"

    def test_planned_components(
        self,
        sample_project: ProjectMetadata,
        active_component: ComponentEvidence,
        planned_component: ComponentEvidence,
    ) -> None:
        bundle = self._create_bundle(
            sample_project,
            components=(active_component, planned_component),
        )

        planned = bundle.planned_components
        assert len(planned) == 1
        assert planned[0].key == "wildside-ingestion"

    def test_components_with_reports(
        self,
        sample_project: ProjectMetadata,
        active_component: ComponentEvidence,
        planned_component: ComponentEvidence,
        deprecated_component: ComponentEvidence,
    ) -> None:
        bundle = self._create_bundle(
            sample_project,
            components=(
                active_component,
                planned_component,
                deprecated_component,
            ),
        )

        with_reports = bundle.components_with_reports
        assert len(with_reports) == 1
        assert with_reports[0].key == "wildside-core"

    def test_blocked_dependencies(self, sample_project: ProjectMetadata) -> None:
        deps = (
            ComponentDependencyEvidence(
                from_component="wildside-core",
                to_component="wildside-engine",
                relationship="depends_on",
                kind="runtime",
            ),
            ComponentDependencyEvidence(
                from_component="wildside-engine",
                to_component="ortho-config",
                relationship="blocked_by",
                kind="runtime",
                rationale="Requires config releases.",
            ),
            ComponentDependencyEvidence(
                from_component="wildside-core",
                to_component="wildside-mockup",
                relationship="emits_events_to",
                kind="runtime",
            ),
        )

        bundle = ProjectEvidenceBundle(
            project=sample_project,
            components=(),
            dependencies=deps,
        )

        blocked = bundle.blocked_dependencies
        assert len(blocked) == 1
        assert blocked[0].from_component == "wildside-engine"
        assert blocked[0].to_component == "ortho-config"
