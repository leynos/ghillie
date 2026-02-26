"""Unit tests for project evidence bundle model structures."""

from __future__ import annotations

import collections.abc as cabc
import datetime as dt
import typing as typ

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

EvidenceModel = (
    ProjectMetadata
    | ComponentRepositorySummary
    | ComponentEvidence
    | ComponentDependencyEvidence
    | ProjectEvidenceBundle
)
ModelFactory = cabc.Callable[[], EvidenceModel]
ModelVerifier = cabc.Callable[[EvidenceModel], None]


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
    model_factory: ModelFactory,
    field_to_modify: str,
    new_value: object,
) -> None:
    """Verify all evidence models are frozen msgspec structs."""
    instance = model_factory()
    with pytest.raises(AttributeError, match=r"immutable type"):
        setattr(instance, field_to_modify, new_value)


def _check_project_metadata_roundtrip(decoded: EvidenceModel) -> None:
    assert isinstance(decoded, ProjectMetadata), "Expected ProjectMetadata"
    assert decoded.key == "wildside", "key mismatch"
    assert decoded.name == "Wildside", "name mismatch"
    assert decoded.programme == "df12", "programme mismatch"
    doc_paths = decoded.documentation_paths
    assert doc_paths == ("docs/roadmap.md",), "documentation_paths mismatch"


def _check_component_repo_summary_roundtrip(decoded: EvidenceModel) -> None:
    assert isinstance(decoded, ComponentRepositorySummary), (
        "Expected ComponentRepositorySummary"
    )
    assert decoded.repository_slug == "leynos/wildside", "repository_slug mismatch"
    assert decoded.status == ReportStatus.ON_TRACK, "status mismatch"
    assert decoded.highlights == ("Feature A shipped",), "highlights mismatch"


def _check_component_evidence_roundtrip(decoded: EvidenceModel) -> None:
    assert isinstance(decoded, ComponentEvidence), "Expected ComponentEvidence"
    assert decoded.key == "wildside-core", "key mismatch"
    assert decoded.has_repository is True, "has_repository should be True"
    assert decoded.notes == ("Primary service",), "notes mismatch"


def _check_dependency_evidence_roundtrip(decoded: EvidenceModel) -> None:
    assert isinstance(decoded, ComponentDependencyEvidence), (
        "Expected ComponentDependencyEvidence"
    )
    assert decoded.from_component == "wildside-core", "from_component mismatch"
    assert decoded.relationship == "blocked_by", "relationship mismatch"
    assert decoded.rationale == "Config releases needed.", "rationale mismatch"


def _check_bundle_roundtrip(decoded: EvidenceModel) -> None:
    assert isinstance(decoded, ProjectEvidenceBundle), "Expected ProjectEvidenceBundle"
    assert decoded.project.key == "wildside", "project key mismatch"
    assert decoded.component_count == 2, "expected 2 components"
    assert len(decoded.dependencies) == 1, "expected 1 dependency"
    comps = decoded.components
    assert comps[0].has_repository is True, "first component should have repo"
    assert comps[1].has_repository is False, "second component should lack repo"


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
    model_factory: ModelFactory,
    model_type: type[object],
    verify: ModelVerifier,
) -> None:
    """Verify msgspec encode/decode roundtrip for all evidence models."""
    instance = model_factory()
    encoded = msgspec.json.encode(instance)
    decoded = typ.cast("EvidenceModel", msgspec.json.decode(encoded, type=model_type))
    verify(decoded)


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
    model_factory: ModelFactory,
    field_assertions: dict[str, object],
) -> None:
    """Verify required fields are set correctly for all evidence models."""
    instance = model_factory()
    for field_name, expected in field_assertions.items():
        actual = getattr(instance, field_name)
        assert actual == expected, (
            f"{field_name}: expected {expected!r}, got {actual!r}"
        )


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
    model_factory: ModelFactory,
    default_assertions: dict[str, object],
) -> None:
    """Verify default field values for all evidence models."""
    instance = model_factory()
    for field_name, expected in default_assertions.items():
        actual = getattr(instance, field_name)
        assert actual == expected, (
            f"{field_name}: expected {expected!r}, got {actual!r}"
        )


class TestProjectMetadata:
    """Tests for ProjectMetadata struct."""

    def test_full_construction(self) -> None:
        """All optional fields are populated when provided."""
        metadata = ProjectMetadata(
            key="wildside",
            name="Wildside",
            description="Transactional streaming platform.",
            programme="df12",
            documentation_paths=("docs/roadmap.md", "docs/adr/"),
        )

        assert metadata.description == "Transactional streaming platform.", (
            "description mismatch"
        )
        assert metadata.programme == "df12", "programme mismatch"
        assert metadata.documentation_paths == ("docs/roadmap.md", "docs/adr/"), (
            "documentation_paths mismatch"
        )


class TestComponentRepositorySummary:
    """Tests for ComponentRepositorySummary struct."""

    def test_full_construction(self) -> None:
        """All fields are populated including optional generated_at."""
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

        assert summary.status == ReportStatus.AT_RISK, "status mismatch"
        assert summary.highlights == ("Shipped v2.0",), "highlights mismatch"
        assert summary.risks == ("Tech debt",), "risks mismatch"
        assert summary.next_steps == ("Refactor module X",), "next_steps mismatch"
        assert summary.generated_at == generated, "generated_at mismatch"


class TestComponentEvidence:
    """Tests for ComponentEvidence struct."""

    def test_has_repository_true(self) -> None:
        """Component with repository_slug has has_repository == True."""
        component = ComponentEvidence(
            key="wildside-core",
            name="Wildside Core Service",
            component_type="service",
            lifecycle="active",
            repository_slug="leynos/wildside",
        )

        assert component.has_repository is True, (
            "has_repository should be True with slug"
        )

    def test_has_repository_false(self) -> None:
        """Component without repository_slug has has_repository == False."""
        component = ComponentEvidence(
            key="wildside-ingestion",
            name="Wildside Ingestion Pipeline",
            component_type="data-pipeline",
            lifecycle="planned",
        )

        assert component.has_repository is False, (
            "has_repository should be False without slug"
        )

    def test_full_construction_with_summary(self) -> None:
        """Component with all fields and a repository summary."""
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

        assert component.repository_summary is not None, (
            "repository_summary should be set"
        )
        assert component.repository_summary.status == ReportStatus.ON_TRACK, (
            "status mismatch"
        )
        assert component.notes == ("Primary service",), "notes mismatch"


class TestComponentDependencyEvidence:
    """Tests for ComponentDependencyEvidence struct."""

    def test_full_construction(self) -> None:
        """All fields including optional rationale are populated."""
        dep = ComponentDependencyEvidence(
            from_component="wildside-core",
            to_component="ortho-config",
            relationship="blocked_by",
            kind="runtime",
            rationale="Requires config releases for rollout.",
        )

        assert dep.relationship == "blocked_by", "relationship mismatch"
        assert dep.rationale == "Requires config releases for rollout.", (
            "rationale mismatch"
        )


class TestProjectEvidenceBundle:
    """Tests for ProjectEvidenceBundle struct."""

    @pytest.fixture
    def sample_project(self) -> ProjectMetadata:
        """Return a minimal Wildside project metadata instance."""
        return ProjectMetadata(key="wildside", name="Wildside")

    @pytest.fixture
    def active_component(self) -> ComponentEvidence:
        """Return an active component with a repository summary."""
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
        """Return a planned component without a repository."""
        return ComponentEvidence(
            key="wildside-ingestion",
            name="Wildside Ingestion Pipeline",
            component_type="data-pipeline",
            lifecycle="planned",
        )

    @pytest.fixture
    def deprecated_component(self) -> ComponentEvidence:
        """Return a deprecated component with a repository slug."""
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
        """Create a ProjectEvidenceBundle with the given project and components."""
        return ProjectEvidenceBundle(
            project=project,
            components=components,
            dependencies=dependencies,
        )

    def test_minimal_construction(self, sample_project: ProjectMetadata) -> None:
        """Bundle can be created with only required fields."""
        bundle = ProjectEvidenceBundle(
            project=sample_project,
            components=(),
            dependencies=(),
        )

        assert bundle.project.key == "wildside", "project key mismatch"
        assert bundle.components == (), "components should be empty"
        assert bundle.dependencies == (), "dependencies should be empty"

    def test_default_values(self, sample_project: ProjectMetadata) -> None:
        """Optional fields default to empty tuple and None."""
        bundle = ProjectEvidenceBundle(
            project=sample_project,
            components=(),
            dependencies=(),
        )

        assert bundle.previous_reports == (), "previous_reports should default to empty"
        assert bundle.generated_at is None, "generated_at should default to None"

    def test_component_count(
        self,
        sample_project: ProjectMetadata,
        active_component: ComponentEvidence,
        planned_component: ComponentEvidence,
    ) -> None:
        """Component count reflects the number of components."""
        bundle = self._create_bundle(
            sample_project,
            components=(active_component, planned_component),
        )

        assert bundle.component_count == 2, (
            f"expected 2 components, got {bundle.component_count}"
        )

    def test_active_components(
        self,
        sample_project: ProjectMetadata,
        active_component: ComponentEvidence,
        planned_component: ComponentEvidence,
        deprecated_component: ComponentEvidence,
    ) -> None:
        """Only components with lifecycle 'active' are returned."""
        bundle = self._create_bundle(
            sample_project,
            components=(
                active_component,
                planned_component,
                deprecated_component,
            ),
        )

        active = bundle.active_components
        assert len(active) == 1, f"expected 1 active component, got {len(active)}"
        assert active[0].key == "wildside-core", (
            f"expected wildside-core, got {active[0].key}"
        )

    def test_planned_components(
        self,
        sample_project: ProjectMetadata,
        active_component: ComponentEvidence,
        planned_component: ComponentEvidence,
    ) -> None:
        """Only components with lifecycle 'planned' are returned."""
        bundle = self._create_bundle(
            sample_project,
            components=(active_component, planned_component),
        )

        planned = bundle.planned_components
        assert len(planned) == 1, f"expected 1 planned component, got {len(planned)}"
        assert planned[0].key == "wildside-ingestion", (
            f"expected wildside-ingestion, got {planned[0].key}"
        )

    def test_components_with_reports(
        self,
        sample_project: ProjectMetadata,
        active_component: ComponentEvidence,
        planned_component: ComponentEvidence,
        deprecated_component: ComponentEvidence,
    ) -> None:
        """Only components with a repository summary are returned."""
        bundle = self._create_bundle(
            sample_project,
            components=(
                active_component,
                planned_component,
                deprecated_component,
            ),
        )

        with_reports = bundle.components_with_reports
        assert len(with_reports) == 1, (
            f"expected 1 component with reports, got {len(with_reports)}"
        )
        assert with_reports[0].key == "wildside-core", (
            f"expected wildside-core, got {with_reports[0].key}"
        )

    def test_blocked_dependencies(self, sample_project: ProjectMetadata) -> None:
        """Only edges with relationship 'blocked_by' are returned."""
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
        assert len(blocked) == 1, f"expected 1 blocked dependency, got {len(blocked)}"
        assert blocked[0].from_component == "wildside-engine", (
            f"expected from wildside-engine, got {blocked[0].from_component}"
        )
        assert blocked[0].to_component == "ortho-config", (
            f"expected to ortho-config, got {blocked[0].to_component}"
        )
