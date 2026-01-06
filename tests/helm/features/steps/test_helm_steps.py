"""BDD steps for Ghillie Helm chart testing."""

from __future__ import annotations

import shutil
import subprocess
import typing as typ
from pathlib import Path

import pytest
from pytest_bdd import given, scenario, then, when
from ruamel.yaml import YAML


class HelmContext(typ.TypedDict, total=False):
    """Shared state for Helm BDD steps."""

    chart_path: Path
    values_file: Path | None
    rendered_docs: list[dict]
    lint_result: subprocess.CompletedProcess[str]


def _find_repo_root() -> Path:
    """Locate repository root by finding pyproject.toml."""
    current = Path(__file__).resolve()
    for parent in (current, *current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    msg = "Repository root not found"
    raise FileNotFoundError(msg)


def _skip_if_no_helm() -> None:
    """Skip test if helm is not installed."""
    if shutil.which("helm") is None:
        pytest.skip("helm is not installed")


@scenario("../helm_chart.feature", "Chart renders valid manifests with default values")
def test_chart_default_rendering() -> None:
    """Scenario wrapper for default rendering test."""


@scenario("../helm_chart.feature", "Chart supports local k3d configuration")
def test_chart_local_config() -> None:
    """Scenario wrapper for local k3d config test."""


@scenario("../helm_chart.feature", "Chart supports GitOps preview configuration")
def test_chart_gitops_config() -> None:
    """Scenario wrapper for GitOps config test."""


@scenario("../helm_chart.feature", "Chart passes Helm lint validation")
def test_chart_lint() -> None:
    """Scenario wrapper for lint test."""


@pytest.fixture
def helm_context() -> HelmContext:
    """Provide shared state between BDD steps."""
    return {}


@given("the Ghillie Helm chart")
def given_helm_chart(helm_context: HelmContext) -> None:
    """Set up the Helm chart path."""
    _skip_if_no_helm()
    root = _find_repo_root()
    helm_context["chart_path"] = root / "charts" / "ghillie"
    helm_context["values_file"] = None


@given("local k3d values with hostless ingress")
def given_local_values(helm_context: HelmContext) -> None:
    """Use local values fixture."""
    fixtures = Path(__file__).resolve().parent.parent.parent / "fixtures"
    helm_context["values_file"] = fixtures / "values_local.yaml"


@given("GitOps values with explicit hostname and external secrets")
def given_gitops_values(helm_context: HelmContext) -> None:
    """Use GitOps values fixture."""
    fixtures = Path(__file__).resolve().parent.parent.parent / "fixtures"
    helm_context["values_file"] = fixtures / "values_gitops.yaml"


@when("I render templates with default values")
def when_render_default(helm_context: HelmContext) -> None:
    """Render Helm templates with defaults."""
    _render_templates(helm_context)


@when("I render templates with provided values")
def when_render_with_values(helm_context: HelmContext) -> None:
    """Render Helm templates with provided values file."""
    _render_templates(helm_context)


def _render_templates(helm_context: HelmContext) -> None:
    """Render Helm templates and store parsed docs."""
    cmd = ["helm", "template", "test-release", str(helm_context["chart_path"])]

    if helm_context.get("values_file"):
        cmd.extend(["--values", str(helm_context["values_file"])])

    result = subprocess.run(  # noqa: S603 - static helm invocation
        cmd, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"Template failed: {result.stderr}"

    yaml_parser = YAML()
    yaml_parser.preserve_quotes = True
    docs = list(yaml_parser.load_all(result.stdout))
    helm_context["rendered_docs"] = [d for d in docs if d is not None]


@when("I run helm lint")
def when_helm_lint(helm_context: HelmContext) -> None:
    """Run helm lint on the chart."""
    result = subprocess.run(  # noqa: S603 - static helm invocation
        ["helm", "lint", str(helm_context["chart_path"])],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    helm_context["lint_result"] = result


@then("the rendered manifests include a Deployment")
def then_has_deployment(helm_context: HelmContext) -> None:
    """Verify Deployment is rendered."""
    kinds = {d["kind"] for d in helm_context["rendered_docs"]}
    assert "Deployment" in kinds


@then("the rendered manifests include a Service")
def then_has_service(helm_context: HelmContext) -> None:
    """Verify Service is rendered."""
    kinds = {d["kind"] for d in helm_context["rendered_docs"]}
    assert "Service" in kinds


@then("the rendered manifests include an Ingress")
def then_has_ingress(helm_context: HelmContext) -> None:
    """Verify Ingress is rendered."""
    kinds = {d["kind"] for d in helm_context["rendered_docs"]}
    assert "Ingress" in kinds


@then("the rendered manifests include a ServiceAccount")
def then_has_serviceaccount(helm_context: HelmContext) -> None:
    """Verify ServiceAccount is rendered."""
    kinds = {d["kind"] for d in helm_context["rendered_docs"]}
    assert "ServiceAccount" in kinds


@then("the Ingress has no host specified")
def then_ingress_hostless(helm_context: HelmContext) -> None:
    """Verify Ingress has no host (for k3d)."""
    ingresses = [d for d in helm_context["rendered_docs"] if d["kind"] == "Ingress"]
    rules = ingresses[0]["spec"]["rules"]
    # Empty host means no host key or empty string
    assert "host" not in rules[0] or not rules[0].get("host")


@then("the Deployment uses the local image tag")
def then_local_image_tag(helm_context: HelmContext) -> None:
    """Verify Deployment uses 'local' tag."""
    deployments = [
        d for d in helm_context["rendered_docs"] if d["kind"] == "Deployment"
    ]
    container = deployments[0]["spec"]["template"]["spec"]["containers"][0]
    assert container["image"].endswith(":local")


@then("the Ingress uses the configured hostname")
def then_ingress_hostname(helm_context: HelmContext) -> None:
    """Verify Ingress has explicit hostname."""
    ingresses = [d for d in helm_context["rendered_docs"] if d["kind"] == "Ingress"]
    rules = ingresses[0]["spec"]["rules"]
    assert rules[0].get("host") is not None
    assert rules[0]["host"] != ""
    assert rules[0]["host"] == "pr-123.preview.example.com"


@then("an ExternalSecret is rendered")
def then_has_externalsecret(helm_context: HelmContext) -> None:
    """Verify ExternalSecret is rendered."""
    kinds = {d["kind"] for d in helm_context["rendered_docs"]}
    assert "ExternalSecret" in kinds


@then("the Deployment references the external secret")
def then_deployment_uses_externalsecret(helm_context: HelmContext) -> None:
    """Verify Deployment uses the secret created by ExternalSecret."""
    deployments = [
        d for d in helm_context["rendered_docs"] if d["kind"] == "Deployment"
    ]
    external_secrets = [
        d for d in helm_context["rendered_docs"] if d["kind"] == "ExternalSecret"
    ]

    es_target = external_secrets[0]["spec"]["target"]["name"]
    container = deployments[0]["spec"]["template"]["spec"]["containers"][0]
    env_from = container.get("envFrom", [])
    secret_refs = [e["secretRef"]["name"] for e in env_from if "secretRef" in e]

    assert es_target in secret_refs


@then("lint passes without errors")
def then_lint_passes(helm_context: HelmContext) -> None:
    """Verify helm lint passes."""
    result = helm_context["lint_result"]
    assert result.returncode == 0, f"Lint failed: {result.stdout}\n{result.stderr}"
