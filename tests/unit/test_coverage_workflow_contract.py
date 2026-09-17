"""Guard the main-owned CodeScene coverage boundary."""

import typing as typ
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
MAIN_PATH = ROOT / ".github" / "workflows" / "coverage-main.yml"
GENERATE_ACTION = "leynos/shared-actions/.github/actions/generate-coverage"
UPLOAD_ACTION = "leynos/shared-actions/.github/actions/upload-codescene-coverage"
ACTION_REVISION = "152d9c4784d0ae5877938a984fe6d1f04d718fd8"


def _workflow(path: Path) -> dict[str, object]:
    """Load a workflow and normalize PyYAML's YAML 1.1 ``on`` key."""
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), f"{path} must contain a mapping"
    if True in workflow:
        workflow["on"] = workflow.pop(True)
    return typ.cast("dict[str, object]", workflow)


def _mapping(value: object, message: str) -> dict[str, object]:
    """Return a validated string-keyed workflow mapping."""
    assert isinstance(value, dict), message
    return typ.cast("dict[str, object]", value)


def _job(workflow: dict[str, object], name: str) -> dict[str, object]:
    """Return a named workflow job."""
    jobs = _mapping(workflow.get("jobs"), "workflow must declare jobs")
    return _mapping(jobs.get(name), f"workflow must declare {name!r}")


def _step(job: dict[str, object], name: str) -> dict[str, object]:
    """Return a named job step."""
    steps = job.get("steps")
    assert isinstance(steps, list), "job must declare steps"
    for candidate in steps:
        if not isinstance(candidate, dict):
            continue
        step = typ.cast("dict[str, object]", candidate)
        if step.get("name") == name:
            return step
    message = f"job must declare {name!r}"
    raise AssertionError(message)


def _inputs(step: dict[str, object], action: str) -> dict[str, object]:
    """Return inputs after validating an exact action revision."""
    uses = step.get("uses")
    assert uses == f"{action}@{ACTION_REVISION}"
    return _mapping(step.get("with"), "action must declare inputs")


def test_pull_request_coverage_is_local_and_ratcheted() -> None:
    """Keep pull-request coverage free of CodeScene credentials and tools."""
    workflow = _workflow(CI_PATH)
    triggers = _mapping(workflow.get("on"), "ci.yml must declare triggers")
    assert "pull_request" in triggers
    lint_test = _job(workflow, "lint-test")
    checkout = _step(lint_test, "Check out repository")
    checkout_inputs = _mapping(checkout.get("with", {}), "checkout inputs")
    assert checkout_inputs.get("fetch-depth") not in {0, "0"}
    coverage = _step(lint_test, "Generate coverage")
    assert coverage.get("if") == "github.event_name == 'pull_request'"
    inputs = _inputs(coverage, GENERATE_ACTION)
    assert inputs.get("python-source") == "./ghillie"
    assert inputs.get("baseline-python-file") == (
        ".coverage-baseline.python-main-owned"
    )
    assert inputs.get("pytest-workers") == ""
    assert inputs.get("with-ratchet") == "true"
    ci_text = CI_PATH.read_text(encoding="utf-8")
    assert "CS_ACCESS_TOKEN" not in ci_text
    assert "upload-codescene-coverage" not in ci_text
    assert "cs-coverage" not in ci_text


def test_main_coverage_publishes_the_local_measurement() -> None:
    """Require main-only publication and explicit CodeScene upload mode."""
    workflow = _workflow(MAIN_PATH)
    assert workflow.get("on") == {
        "push": {"branches": ["main"]},
        "workflow_dispatch": None,
    }
    coverage_upload = _job(workflow, "coverage-upload")
    generate = _inputs(_step(coverage_upload, "Generate coverage"), GENERATE_ACTION)
    assert generate.get("python-source") == "./ghillie"
    assert generate.get("baseline-python-file") == (
        ".coverage-baseline.python-main-owned"
    )
    assert generate.get("pytest-workers") == ""
    assert generate.get("with-ratchet") == "true"
    upload = _inputs(
        _step(coverage_upload, "Upload coverage data to CodeScene"), UPLOAD_ACTION
    )
    assert upload.get("mode") == "upload"
