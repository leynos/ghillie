"""Contract tests for the blocking Skylos dead-code lint gate."""

import shutil
import subprocess
import tomllib
import typing as typ
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict[str, object]:
    """Load the repository's Python project configuration."""
    return tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )


def test_skylos_is_a_pinned_external_tool() -> None:
    """Keep Skylos out of the project environment and pin its tool release."""
    config = _pyproject()
    dependency_groups = typ.cast("dict[str, list[str]]", config["dependency-groups"])

    assert not any(
        dependency.startswith("skylos") for dependency in dependency_groups["dev"]
    )
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "SKYLOS_VERSION = 4.33.2" in makefile
    assert "--from 'skylos==$(SKYLOS_VERSION)' skylos" in makefile


def test_make_lint_runs_a_blocking_production_dead_code_scan() -> None:
    """Keep dead-code analysis local, deterministic, and production-only."""
    make_executable = shutil.which("make")
    assert make_executable is not None

    result = subprocess.run(  # noqa: S603 - test executes make without a shell
        [make_executable, "--no-print-directory", "--dry-run", "lint"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    dry_run = " ".join(result.stdout.replace("\\\n", " ").split())
    assert dry_run.count("skylos --config-file pyproject.toml") == 1
    assert "skylos --config-file pyproject.toml ghillie" in dry_run
    assert "skylos --config-file pyproject.toml ghillie tests" not in dry_run
    assert (
        "--category dead_code --gate --format concise --no-upload "
        "--no-provenance --no-grep-verify" in dry_run
    )


def test_skylos_allow_uses_the_whitelist_subcommand_contract() -> None:
    """Keep `whitelist` ahead of its name and separate from scan options."""
    make_executable = shutil.which("make")
    assert make_executable is not None

    result = subprocess.run(  # noqa: S603 - test executes make without a shell
        [
            make_executable,
            "--no-print-directory",
            "--dry-run",
            "skylos-allow",
            "NAME=registered_handler",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    whitelist_commands = [
        line for line in result.stdout.splitlines() if "skylos whitelist" in line
    ]
    assert len(whitelist_commands) == 1
    whitelist_command = whitelist_commands[0]
    assert "--config-file" not in whitelist_command
    assert "--reason" not in whitelist_command
    assert whitelist_command.endswith('skylos whitelist "${SKYLOS_NAME}"')


def test_skylos_configuration_enables_strict_dead_code_gates() -> None:
    """Require reviewed Skylos configuration for the blocking gate."""
    config = _pyproject()
    tool_config = typ.cast("dict[str, object]", config["tool"])
    skylos = typ.cast("dict[str, object]", tool_config["skylos"])
    gate = typ.cast("dict[str, object]", skylos["gate"])

    assert gate["strict"] is True


def test_skylos_entrypoints_document_verified_dynamic_callers() -> None:
    """Keep static-analysis false positives narrowly and explicitly allowed."""
    config = _pyproject()
    tool_config = typ.cast("dict[str, object]", config["tool"])
    skylos = typ.cast("dict[str, object]", tool_config["skylos"])
    dead_code = typ.cast("dict[str, object]", skylos["dead_code"])
    entrypoints = typ.cast("list[dict[str, object]]", dead_code["entrypoints"])
    configured_names = {
        full_name
        for entrypoint in entrypoints
        for full_name in typ.cast("list[str]", entrypoint["full_name"])
    }

    assert {
        "ghillie.bronze.storage.UTCDateTime.process_bind_param",
        "ghillie.evidence.event_targets.EventTargetExtractor.extract",
        "ghillie.evidence.models.ComponentEvidence.component_type",
    } <= configured_names
    assert all(
        isinstance(reason := entrypoint.get("reason"), str) and reason.strip()
        for entrypoint in entrypoints
    )


def test_ci_runs_the_skylos_enabled_lint_target() -> None:
    """Keep CI aligned with the local dead-code lint gate."""
    workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )

    assert "Run architecture, dead-code, and lint checks" in workflow
    assert "run: make lint" in workflow


def test_skylos_cache_is_ignored() -> None:
    """Keep local Skylos cache files out of version control."""
    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".skylos/" in gitignore.splitlines()
