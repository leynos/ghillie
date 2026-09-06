"""Contract tests for the tool versions the CI workflow depends on.

`main` was red at "Check formatting" because `uv tool install ruff` followed
upstream into a release that formats Python inside Markdown fences, against a
tree formatted by an older one. Nothing in the repository could have caught
that: the workflow named a tool, not a version, and the Makefile ran whichever
ruff happened to be on PATH.

These tests close both holes. They assert the install commands themselves, not
a comment or a step name near them, and each carries a mutation check so a
pattern that quietly matched nothing cannot pass vacuously.
"""

from __future__ import annotations

import re
import typing as typ
from pathlib import Path

import pytest
import yaml

if typ.TYPE_CHECKING:
    import collections.abc as cabc

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"
MAKEFILE_PATH = REPOSITORY_ROOT / "Makefile"
PYPROJECT_PATH = REPOSITORY_ROOT / "pyproject.toml"

pytestmark = pytest.mark.skipif(
    not WORKFLOW_PATH.exists(),
    reason=(
        "workflow file not present in this working copy (for example inside "
        "mutmut's mutants/ sandbox, which does not copy .github/)"
    ),
)

# `uv tool install X`, `npm install -g X`, `bun install -g X`. The capture is
# the rest of the line, quotes included.
INSTALL_PATTERNS = (
    re.compile(r"\buv tool install\s+(?P<arguments>.+)$", re.MULTILINE),
    re.compile(r"\bnpm install -g\s+(?P<arguments>.+)$", re.MULTILINE),
    re.compile(r"\bbun install -g\s+(?P<arguments>.+)$", re.MULTILINE),
)

# A pinned argument is `name==version` or `name@version`, where the version may
# be a shell expansion of a variable holding one.
PINNED = re.compile(r"^[A-Za-z0-9._-]+(==|@)\S+$")

RUFF_VERSION_RE = re.compile(r"^RUFF_VERSION \?= (?P<version>\S+)$", re.MULTILINE)
RUFF_REQUIREMENT_RE = re.compile(r'"ruff==(?P<version>[^"]+)"')
# Every ruff invocation in a recipe must go through the $(RUFF) variable.
BARE_RUFF_RE = re.compile(r"^\t@?ruff\b", re.MULTILINE)


def _install_arguments(text: str) -> cabc.Iterator[tuple[str, str]]:
    """Yield every (install command, package argument) pair in ``text``."""
    for pattern in INSTALL_PATTERNS:
        for match in pattern.finditer(text):
            for token in match.group("arguments").split():
                if token.startswith("-"):
                    continue
                yield match.group(0).strip(), token.strip("\"'")


def _run_steps() -> str:
    """Concatenate every `run:` script in the workflow."""
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), "the workflow must be a mapping"
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "the workflow must declare a jobs mapping"
    scripts = [
        step["run"]
        for job in jobs.values()
        if isinstance(job, dict)
        for step in job.get("steps", [])
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]
    assert scripts, "the workflow declares no run: steps"
    return "\n".join(scripts)


def test_the_workflow_installs_tools_at_all() -> None:
    """Guard the patterns: one that matches nothing would prove nothing."""
    assert list(_install_arguments(_run_steps()))


@pytest.mark.parametrize(
    ("command", "package"),
    list(_install_arguments(_run_steps())),
    ids=lambda value: value.replace(" ", "-"),
)
def test_every_installed_tool_names_a_version(command: str, package: str) -> None:
    """Every package the workflow installs is pinned to an exact version."""
    resolved = re.sub(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", "0.0.0", package)
    assert PINNED.match(resolved), f"{command!r} installs {package!r} unpinned"


def test_the_pin_assertion_rejects_an_unpinned_install() -> None:
    """Mutation check for the assertion above."""
    packages = [package for _, package in _install_arguments("  uv tool install ruff")]

    assert packages == ["ruff"]
    assert not PINNED.match(packages[0])


def test_the_makefile_pins_ruff_and_routes_every_gate_through_it() -> None:
    """One ruff version serves formatting, linting and the spelling helper."""
    makefile = MAKEFILE_PATH.read_text(encoding="utf-8")
    match = RUFF_VERSION_RE.search(makefile)

    assert match is not None, "RUFF_VERSION is not pinned in the Makefile"
    assert re.fullmatch(r"\d+\.\d+\.\d+", match.group("version")), (
        f"RUFF_VERSION must be an exact version, got {match.group('version')!r}"
    )
    assert not BARE_RUFF_RE.search(makefile), (
        "a Makefile recipe calls ruff from PATH instead of $(RUFF); the version "
        "it gets is then whatever the machine happens to have"
    )


def test_the_bare_ruff_assertion_rejects_a_path_invocation() -> None:
    """Mutation check: a recipe line calling ruff from PATH must be caught."""
    assert BARE_RUFF_RE.search("check-fmt:\n\truff format --check\n")
    assert not BARE_RUFF_RE.search("check-fmt:\n\t$(RUFF) format --check\n")


def test_the_project_requirement_matches_the_makefile_pin() -> None:
    """The virtual environment's ruff is the version the gates run.

    Two pins for one tool drift silently, and the drift only shows up as a
    formatting diff nobody asked for.
    """
    makefile_match = RUFF_VERSION_RE.search(MAKEFILE_PATH.read_text(encoding="utf-8"))
    project_match = RUFF_REQUIREMENT_RE.search(
        PYPROJECT_PATH.read_text(encoding="utf-8")
    )

    assert makefile_match is not None, "RUFF_VERSION is not pinned in the Makefile"
    assert project_match is not None, "pyproject.toml does not pin ruff exactly"
    assert makefile_match.group("version") == project_match.group("version")
