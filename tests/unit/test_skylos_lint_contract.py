"""Contract tests for Skylos dead-code detection in Make and CI.

Skylos's scan options and ``whitelist`` subcommand have different command
shapes. Makeutil parses the Makefile into structured rules and variables so
these tests check that public interface without matching incidental whitespace.
Skylos also parses source with its own Python AST, so the CLI must use Python
3.14 to understand the repository's syntax.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import string
import subprocess
import tomllib
import typing as typ
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from hypothesis import example, given, settings
from hypothesis import strategies as st

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

_MAKEUTIL_COMMAND: typ.Final = ("makeutil", "parse", "Makefile")
_MAKEUTIL_REVISION: typ.Final = "29fc5a1634ffbaa18a773eed9dff1b2838a45d9c"
_MAKEUTIL_TOOLCHAIN: typ.Final = "nightly-2026-05-28"
_SHELL_ARGUMENT_TEXT: typ.Final = st.builds(
    lambda prefix, content, suffix: prefix + content + suffix,
    st.text(alphabet=" \t", max_size=4),
    st.text(
        alphabet=string.ascii_letters + string.digits + "_$;|&'\"()[]{}*?!\\`",
        min_size=1,
        max_size=40,
    ),
    st.text(alphabet=" \t", max_size=4),
)
_MAKEUTIL_INSTALL_TOKENS: typ.Final = (
    "rustup",
    "toolchain",
    "install",
    "${MAKEUTIL_TOOLCHAIN}",
    "--profile",
    "minimal",
    "RUSTFLAGS=-Zpolonius=next",
    "cargo",
    "+${MAKEUTIL_TOOLCHAIN}",
    "install",
    "--git",
    "https://github.com/leynos/makeutil",
    "--rev",
    "${MAKEUTIL_REVISION}",
    "--locked",
    "--force",
    "makeutil",
)
_RUNTIME_ENTRY_POINTS: typ.Final = {
    "method": frozenset(
        {
            "ghillie.bronze.storage.UTCDateTime.process_bind_param",
            "ghillie.bronze.storage.UTCDateTime.process_result_value",
            "ghillie.evidence.event_targets.EventTargetExtractor.extract",
        }
    ),
    "parameter": frozenset(
        {
            "ghillie.bronze.storage.UTCDateTime.process_bind_param.dialect",
            "ghillie.bronze.storage.UTCDateTime.process_result_value.dialect",
        }
    ),
    "variable": frozenset(
        {
            "ghillie.bronze.storage.UTCDateTime.impl",
            "ghillie.bronze.storage.UTCDateTime.cache_ok",
            "ghillie.evidence.models.ComponentEvidence.component_type",
        }
    ),
}


def _makefile_report() -> dict[str, object]:
    """Return Makeutil's complete, successfully parsed Makefile report."""
    completed = subprocess.run(  # noqa: S603 - fixed parser command.
        _MAKEUTIL_COMMAND,
        capture_output=True,
        check=True,
        cwd=REPOSITORY_ROOT,
        text=True,
    )
    report = typ.cast("dict[str, object]", json.loads(completed.stdout))
    parse = _mapping(report.get("parse"), subject="Makeutil parse report")
    assert parse.get("status") == "complete", (
        f"Makeutil must complete the Makefile parse, got {parse!r}"
    )
    return report


def _mapping(value: object, *, subject: str) -> dict[str, object]:
    """Return a JSON object, naming the unexpected `subject` on failure."""
    assert isinstance(value, dict), f"expected {subject} to be a JSON object"
    return typ.cast("dict[str, object]", value)


def _objects(value: object, *, subject: str) -> list[dict[str, object]]:
    """Return a JSON object array, naming the unexpected `subject` on failure."""
    assert isinstance(value, list), f"expected {subject} to be a JSON array"
    return [_mapping(item, subject=f"{subject} item") for item in value]


def _text_sequence(value: object, *, subject: str) -> tuple[str, ...]:
    """Return a JSON string array, naming the unexpected `subject` on failure."""
    assert isinstance(value, list), f"expected {subject} to be a JSON array"
    assert all(isinstance(item, str) for item in value), (
        f"expected {subject} to contain only JSON strings"
    )
    return tuple(typ.cast("list[str]", value))


def _sole_variable(name: str) -> dict[str, object]:
    """Return Makeutil's sole variable fact for `name`."""
    variables = _objects(_makefile_report().get("variables"), subject="variables")
    matches = [variable for variable in variables if variable.get("name") == name]
    assert len(matches) == 1, (
        f"expected one Makefile variable named {name!r}, found {len(matches)}"
    )
    return matches[0]


def _sole_recipe_rule(target: str) -> dict[str, object]:
    """Return the only parsed rule for `target` that has recipes."""
    rules = _objects(_makefile_report().get("rules"), subject="rules")
    matches = [
        rule
        for rule in rules
        if target in _text_sequence(rule.get("targets"), subject="rule targets")
        and _objects(rule.get("recipes"), subject="rule recipes")
    ]
    assert len(matches) == 1, (
        f"expected one recipe-bearing Makefile rule named {target!r}, found "
        f"{len(matches)}"
    )
    return matches[0]


def _variable_tokens(name: str) -> tuple[str, ...]:
    """Return shell-like tokens from Makeutil's raw variable value."""
    value = _sole_variable(name).get("raw_value")
    assert isinstance(value, str), f"expected {name!r} to have a string value"
    return tuple(shlex.split(value))


def _recipe_tokens(target: str) -> tuple[tuple[str, ...], ...]:
    """Return shell-like tokens for every recipe in `target`."""
    recipes = _objects(
        _sole_recipe_rule(target).get("recipes"), subject=f"{target} recipes"
    )
    return tuple(
        tuple(fragment for fragment in shlex.split(recipe_text) if fragment != "\n")
        for recipe in recipes
        if isinstance(recipe_text := recipe.get("text"), str)
    )


def _workflow_job(workflow_path: str, job_name: str) -> dict[str, object]:
    """Return the named job from a repository workflow."""
    workflow = yaml.safe_load((REPOSITORY_ROOT / workflow_path).read_text())
    workflow_mapping = _mapping(workflow, subject=f"{workflow_path} workflow")
    jobs = _mapping(workflow_mapping.get("jobs"), subject=f"{workflow_path} jobs")
    return _mapping(jobs.get(job_name), subject=f"{workflow_path} job {job_name!r}")


def _sole_workflow_step(
    job_name: str,
    step_name: str,
    *,
    workflow_path: str = ".github/workflows/ci.yml",
) -> dict[str, object]:
    """Return the sole named CI step from `job_name`."""
    job = _workflow_job(workflow_path, job_name)
    steps = _objects(
        job.get("steps"), subject=f"{workflow_path} job {job_name!r} steps"
    )
    matches = [step for step in steps if step.get("name") == step_name]
    assert len(matches) == 1, (
        f"expected one {step_name!r} step in {workflow_path} job {job_name!r}, "
        f"found {len(matches)}"
    )
    return matches[0]


def _run_skylos_allow(
    *, symbol: str | None = None, reason: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the whitelist input boundary without invoking Skylos."""
    environment: dict[str, str] = dict(os.environ)
    environment["NAME"] = "wsl-hostname"
    environment.pop("REASON", None)
    environment.pop("SYMBOL", None)
    if symbol is not None:
        environment["SYMBOL"] = symbol
    if reason is not None:
        environment["REASON"] = reason
    command: list[str] = [
        _make_executable(),
        f"SKYLOS_CLI={_true_executable()}",
        "skylos-allow",
    ]
    return subprocess.run(  # noqa: S603 - controlled Make test command.
        command,
        capture_output=True,
        check=False,
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
    )


def _make_executable() -> str:
    """Return the absolute Make executable path required by boundary tests."""
    executable = shutil.which("make")
    assert executable is not None, "Skylos contract tests require GNU Make"
    return executable


def _true_executable() -> str:
    """Return an executable that proves invalid requests never run Skylos."""
    executable = shutil.which("true")
    assert executable is not None, "Skylos contract tests require true on PATH"
    return executable


def _assert_makeutil_installation(command: object, *, contract: str) -> None:
    """Assert that `command` installs the pinned Makeutil parser."""
    assert isinstance(command, str), (
        f"{contract} must provide a Makeutil installation shell command"
    )
    assert (
        tuple(shlex.split(command.replace("\\\n", ""))) == _MAKEUTIL_INSTALL_TOKENS
    ), f"{contract} must pin the Makeutil installation command"


def test_lint_recipe_runs_the_production_dead_code_gate() -> None:
    """`make lint` must scan production code with Skylos's strict gate."""
    assert _variable_tokens("SKYLOS_VERSION") == ("4.33.2",), (
        "Skylos version contract must pin 4.33.2"
    )
    assert _variable_tokens("SKYLOS_PRODUCTION_TARGETS") == ("ghillie",), (
        "Skylos production-target contract must scan ghillie"
    )
    assert _variable_tokens("SKYLOS_EXCLUDE_FOLDERS") == ("tests",), (
        "Skylos exclusion contract must omit tests"
    )
    skylos_commands = [
        command for command in _recipe_tokens("lint") if command[:1] == ("$(SKYLOS)",)
    ]
    assert skylos_commands == [
        (
            "$(SKYLOS)",
            "$(SKYLOS_PRODUCTION_TARGETS)",
            "--exclude",
            "$(SKYLOS_EXCLUDE_FOLDERS)",
            "--category",
            "dead_code",
            "--gate",
            "--format",
            "concise",
            "--no-upload",
            "--no-provenance",
            "--no-grep-verify",
        )
    ], "Skylos lint command contract must scan production dead code strictly"


def test_whitelist_target_uses_the_python_314_cli_contract() -> None:
    """`skylos whitelist` must dispatch before its reason and scan options."""
    assert _variable_tokens("SKYLOS_CLI") == (
        "$(UV_ENV)",
        "uv",
        "tool",
        "run",
        "--python",
        "3.14",
        "--from",
        "skylos==$(SKYLOS_VERSION)",
        "skylos",
    ), "Skylos CLI contract must pin Python 3.14 and its tool release"
    assert _variable_tokens("SKYLOS") == (
        "$(SKYLOS_CLI)",
        "--config-file",
        "pyproject.toml",
    ), "Skylos scan command contract must add only the configuration file"
    whitelist_commands = [
        command
        for command in _recipe_tokens("skylos-allow")
        if command[:1] == ("$(SKYLOS_CLI)",)
    ]
    assert whitelist_commands == [
        (
            "$(SKYLOS_CLI)",
            "whitelist",
            "$${SKYLOS_SYMBOL}",
            "--reason",
            "$${SKYLOS_REASON}",
        )
    ], "Skylos whitelist command contract must dispatch before --reason"


@settings(max_examples=25, deadline=None)
@given(value=st.text(alphabet=" \t\n", min_size=1, max_size=8))
def test_skylos_allow_rejects_missing_or_whitespace_values(value: str) -> None:
    """The whitelist target must reject absent and whitespace-only inputs."""
    requests = (
        ({}, "SYMBOL"),
        ({"symbol": "handler"}, "REASON"),
        ({"symbol": value, "reason": "runtime caller"}, "SYMBOL"),
        ({"symbol": "handler", "reason": value}, "REASON"),
    )
    for arguments, missing_name in requests:
        completed = _run_skylos_allow(**arguments)
        assert completed.returncode == 2, (
            f"Skylos whitelist boundary must reject missing or whitespace-only "
            f"{missing_name} despite the injected WSL NAME"
        )
        assert (
            f"Error: {missing_name} is required for a named whitelist exception"
            in completed.stderr
        ), f"Skylos whitelist boundary must name the missing {missing_name}"


@settings(max_examples=25, deadline=None)
@example(symbol="$(handler);*", reason='Loaded "$plugin" | registry')
@given(symbol=_SHELL_ARGUMENT_TEXT, reason=_SHELL_ARGUMENT_TEXT)
def test_skylos_allow_forwards_generated_argument_boundaries(
    symbol: str, reason: str
) -> None:
    """Each non-empty value must reach Skylos as exactly one argument."""
    pyproject_path = REPOSITORY_ROOT / "pyproject.toml"
    original_pyproject = pyproject_path.read_bytes()
    with TemporaryDirectory() as temporary_directory:
        recorded_arguments = Path(temporary_directory, "arguments.json")
        recorder = Path(temporary_directory, "skylos-recorder")
        recorder.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import os\n"
            "import sys\n"
            "from pathlib import Path\n\n"
            'Path(os.environ["SKYLOS_ARGUMENTS_PATH"]).write_text(\n'
            "    json.dumps(sys.argv[1:]), encoding='utf-8'\n"
            ")\n",
            encoding="utf-8",
        )
        recorder.chmod(0o755)
        environment = {
            **os.environ,
            "NAME": "wsl-hostname",
            "REASON": reason,
            "SKYLOS_ARGUMENTS_PATH": str(recorded_arguments),
            "SYMBOL": symbol,
        }
        command: list[str] = [
            _make_executable(),
            "--no-print-directory",
            f"SKYLOS_CLI={recorder}",
            "skylos-allow",
        ]
        completed = subprocess.run(  # noqa: S603 - controlled Make contract command.
            command,
            capture_output=True,
            check=False,
            cwd=REPOSITORY_ROOT,
            env=environment,
            text=True,
        )
        assert completed.returncode == 0, (
            "Skylos whitelist must accept each generated non-empty input: "
            f"{completed.stderr}"
        )
        assert recorded_arguments.exists(), (
            "Skylos whitelist must invoke the injected recorder for valid input"
        )
        assert json.loads(recorded_arguments.read_text(encoding="utf-8")) == [
            "whitelist",
            symbol,
            "--reason",
            reason,
        ], "Skylos must receive each generated value as exactly one argument"
    assert pyproject_path.read_bytes() == original_pyproject, (
        "Skylos whitelist forwarding tests must not mutate pyproject.toml"
    )


def test_skylos_configuration_models_implicit_runtime_callers() -> None:
    """Every current false positive must be a typed, explained entry point."""
    with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as configuration_file:
        configuration = tomllib.load(configuration_file)
    tool = _mapping(configuration.get("tool"), subject="tool configuration")
    skylos = _mapping(tool.get("skylos"), subject="Skylos configuration")
    gate = _mapping(skylos.get("gate"), subject="Skylos gate configuration")
    assert gate.get("strict") is True, (
        "Skylos gate configuration must enable strict mode"
    )
    dead_code = _mapping(
        skylos.get("dead_code"), subject="Skylos dead-code configuration"
    )
    entry_points = _objects(dead_code.get("entrypoints"), subject="Skylos entry points")
    configured_by_type: dict[str, set[str]] = {}
    for entry_point in entry_points:
        entry_point_type = entry_point.get("type")
        assert isinstance(entry_point_type, str), (
            "Skylos entry-point contract must classify every runtime caller"
        )
        reason = entry_point.get("reason")
        assert isinstance(reason, str), (
            "Skylos entry-point contract must provide a textual reason"
        )
        assert reason.strip(), (
            "Skylos entry-point contract must provide a non-empty reason"
        )
        configured_by_type.setdefault(entry_point_type, set()).update(
            _text_sequence(entry_point.get("full_name"), subject="entry-point name")
        )
    assert configured_by_type == _RUNTIME_ENTRY_POINTS, (
        "Skylos entry-point contract must preserve typed runtime exclusions"
    )


def test_ci_installs_pinned_makeutil_for_each_full_suite_job() -> None:
    """Every isolated full-suite or coverage job must provision Makeutil."""
    lint_step = _sole_workflow_step(
        "lint-test", "Run architecture, dead-code, and lint checks"
    )
    assert lint_step.get("run") == "make lint", (
        "CI lint-step contract must invoke the shared make lint target"
    )
    for workflow_path, job_name in (
        (".github/workflows/ci.yml", "lint-test"),
        (".github/workflows/coverage-main.yml", "coverage-upload"),
    ):
        job = _workflow_job(workflow_path, job_name)
        environment = _mapping(
            job.get("env"), subject=f"{workflow_path} Makeutil environment"
        )
        assert environment.get("MAKEUTIL_REVISION") == _MAKEUTIL_REVISION, (
            f"{workflow_path} Makeutil revision contract must stay pinned"
        )
        assert environment.get("MAKEUTIL_TOOLCHAIN") == _MAKEUTIL_TOOLCHAIN, (
            f"{workflow_path} Makeutil toolchain contract must stay pinned"
        )
        parser_step = _sole_workflow_step(
            job_name, "Install Makefile parser", workflow_path=workflow_path
        )
        _assert_makeutil_installation(
            parser_step.get("run"),
            contract=f"{workflow_path} Makeutil-install contract",
        )


def test_skylos_cache_is_ignored() -> None:
    """Keep local Skylos cache files out of version control."""
    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".skylos/" in gitignore.splitlines(), (
        "Git ignore contract must exclude the Skylos cache directory"
    )
