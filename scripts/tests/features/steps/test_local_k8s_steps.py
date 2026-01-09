"""Behavioural coverage for the local k3d preview environment lifecycle."""

from __future__ import annotations

import base64
import io
import subprocess
import typing as typ
from contextlib import redirect_stdout

import pytest
from local_k8s import app
from pytest_bdd import given, parsers, scenario, then, when


class LocalK8sContext(typ.TypedDict, total=False):
    """Shared mutable scenario state."""

    cluster_exists: bool
    captured_calls: list[tuple[str, ...]]
    stdout: str
    exit_code: int


class SubprocessMock:
    """Mock for subprocess.run that tracks calls and returns appropriate results."""

    def __init__(self, context: LocalK8sContext, *, cluster_exists: bool) -> None:
        """Initialize the mock with context and cluster state."""
        self.context = context
        self.cluster_exists = cluster_exists
        self._handlers: dict[str, typ.Callable[[list[str]], tuple[str, int]]] = {
            "which": self._handle_which,
            "k3d": self._handle_k3d,
            "kubectl": self._handle_kubectl,
            "helm": self._handle_helm,
            "docker": self._handle_docker,
        }

    def _handle_which(self, args: list[str]) -> tuple[str, int]:
        return f"/usr/bin/{args[1]}", 0

    def _handle_k3d(self, args: list[str]) -> tuple[str, int]:
        if args[1:3] == ["cluster", "list"]:
            # k3d cluster list -o json returns JSON array
            if self.cluster_exists:
                return '[{"name": "ghillie-local"}]', 0
            return "[]", 0
        if args[1:3] == ["kubeconfig", "get"]:
            return "/mock/kubeconfig", 0
        return "", 0  # create, delete, image import

    def _handle_kubectl(self, args: list[str]) -> tuple[str, int]:
        if args[1:3] == ["get", "namespace"]:
            return "", 1  # namespace doesn't exist
        if args[1:3] == ["get", "secret"]:
            return self._handle_kubectl_get_secret(args)
        if args[1:3] == ["get", "pod"]:
            return "NAME           READY   STATUS\nghillie-abc   1/1     Running", 0
        return "", 0  # create, apply, wait, logs, rollout

    def _handle_kubectl_get_secret(self, args: list[str]) -> tuple[str, int]:
        joined = " ".join(args)
        if "-o=jsonpath" in joined:
            if "pg-ghillie" in joined:
                db_url = "postgresql://ghillie:pass@pg-ghillie:5432/ghillie"
                return base64.b64encode(db_url.encode()).decode(), 0
            if "valkey-ghillie" in joined:
                return base64.b64encode(b"valkeypass").decode(), 0
        return "", 0

    def _handle_helm(self, _args: list[str]) -> tuple[str, int]:
        return "", 0  # repo, upgrade, uninstall all succeed

    def _handle_docker(self, _args: list[str]) -> tuple[str, int]:
        return "", 0  # build succeeds

    def __call__(
        self,
        args: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        """Handle a subprocess.run call."""
        # Extract parameters from kwargs with defaults
        check = kwargs.get("check", False)
        capture_output = kwargs.get("capture_output", False)
        text = kwargs.get("text", False)

        self.context["captured_calls"].append(tuple(args))

        handler = self._handlers.get(args[0], lambda _: ("", 0))
        stdout, returncode = handler(args)

        if check and returncode != 0:
            raise subprocess.CalledProcessError(returncode, args, stdout, "")

        return subprocess.CompletedProcess(
            args=args,
            returncode=returncode,
            stdout=stdout if capture_output or text else "",
            stderr="",
        )


# Scenario wrappers
@scenario("../local_k8s.feature", "Create preview environment from scratch")
def test_create_preview_from_scratch() -> None:
    """Wrap the pytest-bdd scenario for creating preview from scratch."""


@scenario("../local_k8s.feature", "Idempotent up reuses existing cluster")
def test_idempotent_up_reuses_cluster() -> None:
    """Wrap the pytest-bdd scenario for idempotent up."""


@scenario("../local_k8s.feature", "Delete preview environment")
def test_delete_preview_environment() -> None:
    """Wrap the pytest-bdd scenario for deleting preview."""


@scenario("../local_k8s.feature", "Status shows pod information")
def test_status_shows_pod_information() -> None:
    """Wrap the pytest-bdd scenario for status command."""


@pytest.fixture
def local_k8s_context() -> LocalK8sContext:
    """Provide shared context for the BDD steps."""
    return {
        "cluster_exists": False,
        "captured_calls": [],
        "stdout": "",
        "exit_code": -1,
    }


# Background step
@given("the CLI tools docker, k3d, kubectl, and helm are available")
def given_tools_available() -> None:
    """Ensure the required CLI tools are considered available (handled by mock)."""


# Given steps
@given(parsers.parse("no k3d cluster named {cluster_name} exists"))
def given_no_cluster_exists(
    local_k8s_context: LocalK8sContext, cluster_name: str
) -> None:
    """Configure context to indicate no cluster exists."""
    local_k8s_context["cluster_exists"] = False


@given(parsers.parse("a k3d cluster named {cluster_name} exists"))
def given_cluster_exists(local_k8s_context: LocalK8sContext, cluster_name: str) -> None:
    """Configure context to indicate cluster already exists."""
    local_k8s_context["cluster_exists"] = True


def _run_command(
    ctx: LocalK8sContext, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    """Execute a CLI command with mocked subprocess and capture output."""
    mock = SubprocessMock(ctx, cluster_exists=ctx.get("cluster_exists", False))
    monkeypatch.setattr("subprocess.run", mock)
    # Mock shutil.which to return a path for all required tools
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    captured = io.StringIO()
    with redirect_stdout(captured):
        try:
            exit_code = app(args)
            ctx["exit_code"] = exit_code if exit_code is not None else 0
        except SystemExit as e:
            ctx["exit_code"] = e.code if isinstance(e.code, int) else 1

    ctx["stdout"] = captured.getvalue()


# When steps
@when("I run local_k8s up")
def when_run_up(
    local_k8s_context: LocalK8sContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execute the up command with mocked subprocess."""
    _run_command(local_k8s_context, monkeypatch, ["up", "--ingress-port=12345"])


@when("I run local_k8s down")
def when_run_down(
    local_k8s_context: LocalK8sContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execute the down command with mocked subprocess."""
    _run_command(local_k8s_context, monkeypatch, ["down"])


@when("I run local_k8s status")
def when_run_status(
    local_k8s_context: LocalK8sContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execute the status command with mocked subprocess."""
    _run_command(local_k8s_context, monkeypatch, ["status"])


# Then steps - assertions on captured calls
def _has_call(ctx: LocalK8sContext, prefix: tuple[str, ...]) -> bool:
    return any(c[: len(prefix)] == prefix for c in ctx["captured_calls"])


def _has_call_containing(
    ctx: LocalK8sContext, prefix: tuple[str, ...], text: str
) -> bool:
    calls = [c for c in ctx["captured_calls"] if c[: len(prefix)] == prefix]
    return any(text in str(c).lower() for c in calls)


@then(parsers.parse("a k3d cluster named {cluster_name} is created"))
def then_cluster_created(local_k8s_context: LocalK8sContext, cluster_name: str) -> None:
    """Verify k3d cluster create was called."""
    assert _has_call_containing(
        local_k8s_context, ("k3d", "cluster", "create"), cluster_name
    ), "Expected k3d cluster create with cluster name"


@then("the CNPG operator is installed")
def then_cnpg_operator_installed(local_k8s_context: LocalK8sContext) -> None:
    """Verify CNPG operator installation was triggered."""
    assert _has_call_containing(local_k8s_context, ("helm",), "cnpg"), (
        "Expected CNPG helm installation"
    )


@then("a CNPG Postgres cluster is created")
def then_cnpg_cluster_created(local_k8s_context: LocalK8sContext) -> None:
    """Verify CNPG Postgres cluster creation via kubectl apply."""
    assert _has_call(local_k8s_context, ("kubectl", "apply")), "Expected kubectl apply"


@then("the Valkey operator is installed")
def then_valkey_operator_installed(local_k8s_context: LocalK8sContext) -> None:
    """Verify Valkey operator installation via Helm was triggered."""
    assert _has_call_containing(local_k8s_context, ("helm",), "valkey"), (
        "Expected Valkey helm installation"
    )


@then("a Valkey instance is created")
def then_valkey_instance_created(local_k8s_context: LocalK8sContext) -> None:
    """Verify Valkey instance creation via kubectl apply."""
    apply_calls = [
        c for c in local_k8s_context["captured_calls"] if c[:2] == ("kubectl", "apply")
    ]
    assert len(apply_calls) >= 2, "Expected multiple kubectl apply calls"


@then("a secret named ghillie exists with DATABASE_URL and VALKEY_URL")
def then_secret_created(local_k8s_context: LocalK8sContext) -> None:
    """Verify secret creation with connection strings."""
    assert _has_call_containing(
        local_k8s_context, ("kubectl", "create", "secret"), "ghillie"
    ), "Expected secret named ghillie"


@then("the Docker image is built and imported")
def then_docker_image_built(local_k8s_context: LocalK8sContext) -> None:
    """Verify Docker image was built and imported to k3d."""
    assert _has_call(local_k8s_context, ("docker", "build")), "Expected docker build"
    assert _has_call(local_k8s_context, ("k3d", "image", "import")), (
        "Expected k3d image import"
    )


@then("the Ghillie Helm chart is installed")
def then_helm_chart_installed(local_k8s_context: LocalK8sContext) -> None:
    """Verify Ghillie Helm chart was installed."""
    assert _has_call_containing(local_k8s_context, ("helm",), "upgrade"), (
        "Expected helm upgrade"
    )


@then("the preview URL is printed to stdout")
def then_preview_url_printed(local_k8s_context: LocalK8sContext) -> None:
    """Verify the preview URL appears in stdout."""
    assert "http://127.0.0.1:" in local_k8s_context["stdout"], (
        "Expected preview URL in stdout"
    )


@then(parsers.parse("the exit code is {code:d}"))
def then_exit_code(local_k8s_context: LocalK8sContext, code: int) -> None:
    """Verify the exit code matches expected."""
    assert local_k8s_context["exit_code"] == code, f"Expected exit code {code}"


@then("the existing cluster is not deleted")
def then_cluster_not_deleted(local_k8s_context: LocalK8sContext) -> None:
    """Verify that k3d cluster delete was not called."""
    assert not _has_call(local_k8s_context, ("k3d", "cluster", "delete")), (
        "Expected no k3d cluster delete"
    )


@then("the Helm release is upgraded")
def then_helm_release_upgraded(local_k8s_context: LocalK8sContext) -> None:
    """Verify Helm release was upgraded."""
    assert _has_call_containing(local_k8s_context, ("helm",), "upgrade"), (
        "Expected helm upgrade"
    )


@then("the k3d cluster is deleted")
def then_cluster_deleted(local_k8s_context: LocalK8sContext) -> None:
    """Verify k3d cluster was deleted."""
    assert _has_call(local_k8s_context, ("k3d", "cluster", "delete")), (
        "Expected k3d delete"
    )


@then("pod status is printed")
def then_pod_status_printed(local_k8s_context: LocalK8sContext) -> None:
    """Verify pod status was queried."""
    assert _has_call(local_k8s_context, ("kubectl", "get", "pods")), (
        "Expected kubectl get pods"
    )
