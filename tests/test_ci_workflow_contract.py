"""Contract tests for the tool versions the CI workflow depends on.

`main` was red at "Check formatting" because `uv tool install ruff` named no
version. Upstream began formatting Python inside Markdown fences and twenty
documentation files stopped matching, on a workflow nobody had touched. The
Makefile made it worse by running whichever `ruff` was on `PATH`, so no local
gate could disagree with CI.

These tests close both holes. They assert the install commands and the recipe
lines themselves, not a comment or a step name near them; they resolve a
version written as `${VAR}` back to the value the step's `env` gives it rather
than assuming a variable holds something exact; and each carries a mutation
check so a pattern that quietly matched nothing cannot pass vacuously.
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

if not WORKFLOW_PATH.exists():
    # An import-time skip, not a `pytestmark`: the parametrised cases below are
    # built while this module is imported, which is before pytest applies a
    # marker. mutmut's `mutants/` sandbox does not copy `.github/`, and reading
    # the workflow there would fail collection rather than skip it.
    pytest.skip(
        "workflow file not present in this working copy",
        allow_module_level=True,
    )

INSTALL_PATTERNS = (
    re.compile(r"\buv tool install\s+(?P<arguments>.+)$", re.MULTILINE),
    re.compile(r"\bnpm install -g\s+(?P<arguments>.+)$", re.MULTILINE),
    re.compile(r"\bbun install -g\s+(?P<arguments>.+)$", re.MULTILINE),
)

# An exact version: digits and dots, optionally a pre-release suffix. A moving
# tag or a range is not a version, so `latest`, `^0.23`, `~=1.2`, `1.*` and any
# comparator are rejected; each would reintroduce the drift the pin prevents.
EXACT_VERSION = r"\d+(?:\.\d+)+(?:[-.][0-9A-Za-z][0-9A-Za-z.]*)?"
PINNED = re.compile(rf"^@?[A-Za-z0-9._/-]+(?:==|@){EXACT_VERSION}$")
SHELL_VARIABLE = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}")

RUFF_VERSION_RE = re.compile(r"^RUFF_VERSION \?= (?P<version>\S+)$", re.MULTILINE)
RUFF_DEFINITION_RE = re.compile(
    r"^RUFF = .*\buv tool run ruff@\$\(RUFF_VERSION\)", re.MULTILINE
)
RUFF_REQUIREMENT_RE = re.compile(r'"ruff==(?P<version>[^"]+)"')
# A recipe line invoking ruff from PATH rather than through $(RUFF).
BARE_RUFF_RE = re.compile(r"^\t@?ruff\b", re.MULTILINE)


class Install(typ.NamedTuple):
    """One package argument of one install command in the workflow."""

    command: str
    package: str
    resolved: str


def _steps() -> cabc.Iterator[tuple[str, dict[str, str]]]:
    """Yield each `run:` script with the environment visible to it.

    A version written as `${VAR}` means nothing without the value behind it, so
    the workflow, job and step `env` mappings are merged in that order of
    increasing precedence and carried alongside the script.
    """
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict), "the workflow must be a mapping"
    workflow_env = _string_mapping(workflow.get("env"))
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "the workflow must declare a jobs mapping"

    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        job_env = workflow_env | _string_mapping(job.get("env"))
        for step in job.get("steps", []):
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                yield step["run"], job_env | _string_mapping(step.get("env"))


def _string_mapping(value: object) -> dict[str, str]:
    """Read an `env:` mapping, keeping only the entries with string values."""
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items() if isinstance(item, str)}


def _resolve(package: str, environment: dict[str, str]) -> str:
    """Substitute every `${VAR}` in ``package`` with the value the step gives it.

    An unresolved variable is left as a marker rather than a plausible version,
    so a misspelt or undefined name fails the pin assertion instead of passing
    it.
    """

    def substitute(match: re.Match[str]) -> str:
        return environment.get(match.group("name"), "<undefined>")

    return SHELL_VARIABLE.sub(substitute, package)


def _installs() -> list[Install]:
    """Every package argument of every install command in the workflow."""
    found: list[Install] = []
    for script, environment in _steps():
        for pattern in INSTALL_PATTERNS:
            for match in pattern.finditer(script):
                command = match.group(0).strip()
                for token in match.group("arguments").split():
                    if token.startswith("-"):
                        continue
                    package = token.strip("\"'")
                    found.append(
                        Install(command, package, _resolve(package, environment))
                    )
    return found


INSTALLS = _installs()


class TestToolPins:
    """Every package the workflow installs names an exact version."""

    def test_the_workflow_installs_tools_at_all(self) -> None:
        """Guard the patterns: one that matches nothing would prove nothing."""
        assert INSTALLS

    @pytest.mark.parametrize(
        "install", INSTALLS, ids=lambda install: install.package.strip("\"'")
    )
    def test_every_installed_tool_names_an_exact_version(
        self, install: Install
    ) -> None:
        """The value behind the variable is a version, not a moving tag.

        Parameters
        ----------
        install : Install
            One install command, its package argument and the argument with
            every `${VAR}` replaced by the value the step's environment gives
            it.

        """
        assert PINNED.match(install.resolved), (
            f"{install.command!r} installs {install.package!r}, "
            f"which resolves to {install.resolved!r}"
        )

    @pytest.mark.parametrize(
        "selector",
        [
            "markdownlint-cli2@latest",
            "markdownlint-cli2@^0.23",
            "markdownlint-cli2@~0.23.0",
            "mbake==1.*",
            "mbake>=1.4.6",
            "mbake==<undefined>",
            "mbake",
        ],
        ids=[
            "latest",
            "caret",
            "tilde",
            "wildcard",
            "lower-bound",
            "undefined",
            "bare",
        ],
    )
    def test_the_pin_assertion_rejects_a_selector_that_is_not_one_version(
        self, selector: str
    ) -> None:
        """Mutation check: every way of not pinning must fail.

        Parameters
        ----------
        selector : str
            A resolved package selector naming something other than one version.

        """
        assert not PINNED.match(selector)

    @pytest.mark.parametrize(
        "selector",
        ["mbake==1.4.6", "markdownlint-cli2@0.23.2", "pajv@1.2.0", "ty==0.0.78"],
        ids=["pypi", "npm", "bun", "two-component"],
    )
    def test_the_pin_assertion_accepts_an_exact_version(self, selector: str) -> None:
        """The shapes the workflow actually uses must still pass.

        Parameters
        ----------
        selector : str
            A resolved package selector naming exactly one version.

        """
        assert PINNED.match(selector)

    def test_an_undefined_variable_does_not_resolve_to_a_version(self) -> None:
        """A misspelt variable name must fail rather than look pinned."""
        assert _resolve("mbake==${TYPO}", {"MBAKE_VERSION": "1.4.6"}) == (
            "mbake==<undefined>"
        )
        assert _resolve("mbake==${MBAKE_VERSION}", {"MBAKE_VERSION": "1.4.6"}) == (
            "mbake==1.4.6"
        )


class TestRuffPin:
    """One pinned ruff serves every gate, and the two pins agree."""

    def test_the_makefile_pins_ruff_to_an_exact_version(self) -> None:
        """`RUFF_VERSION` names one release."""
        match = RUFF_VERSION_RE.search(MAKEFILE_PATH.read_text(encoding="utf-8"))

        assert match is not None, "RUFF_VERSION is not pinned in the Makefile"
        assert re.fullmatch(r"\d+\.\d+\.\d+", match.group("version")), (
            f"RUFF_VERSION must be an exact version, got {match.group('version')!r}"
        )

    def test_the_ruff_variable_invokes_the_pinned_release(self) -> None:
        """`$(RUFF)` must expand to the pin, not to whatever is on `PATH`.

        Without this, redefining `RUFF = ruff` restores the old behaviour while
        leaving every recipe, the version variable and the project requirement
        untouched, so every other assertion here would still pass.
        """
        assert RUFF_DEFINITION_RE.search(MAKEFILE_PATH.read_text(encoding="utf-8")), (
            "RUFF must be defined as `uv tool run ruff@$(RUFF_VERSION)`"
        )

    def test_no_recipe_calls_ruff_from_the_path(self) -> None:
        """A bare `ruff` in a recipe gets whatever the machine happens to have."""
        assert not BARE_RUFF_RE.search(MAKEFILE_PATH.read_text(encoding="utf-8"))

    @pytest.mark.parametrize(
        ("definition", "accepted"),
        [
            ("RUFF = ruff\n", False),
            ("RUFF = $(UV_ENV) uv tool run ruff@0.15.21\n", False),
            ("RUFF = $(UV_ENV) uv tool run ruff@$(RUFF_VERSION)\n", True),
        ],
        ids=["path", "hard-coded-version", "pinned"],
    )
    def test_the_definition_assertion_rejects_an_unpinned_variable(
        self, definition: str, *, accepted: bool
    ) -> None:
        """Mutation check for the definition assertion.

        Parameters
        ----------
        definition : str
            A candidate `RUFF = ...` line.
        accepted : bool
            Whether the assertion should accept it.

        """
        assert bool(RUFF_DEFINITION_RE.search(definition)) is accepted

    def test_the_path_assertion_rejects_a_bare_invocation(self) -> None:
        """Mutation check for the PATH assertion."""
        assert BARE_RUFF_RE.search("check-fmt:\n\truff format --check\n")
        assert not BARE_RUFF_RE.search("check-fmt:\n\t$(RUFF) format --check\n")

    def test_the_project_requirement_matches_the_makefile_pin(self) -> None:
        """The virtual environment's ruff is the version the gates run.

        Two pins for one tool drift silently, and the drift shows up only as a
        formatting or lint diff nobody asked for.
        """
        makefile_match = RUFF_VERSION_RE.search(
            MAKEFILE_PATH.read_text(encoding="utf-8")
        )
        project_match = RUFF_REQUIREMENT_RE.search(
            PYPROJECT_PATH.read_text(encoding="utf-8")
        )

        assert makefile_match is not None, "RUFF_VERSION is not pinned in the Makefile"
        assert project_match is not None, "pyproject.toml does not pin ruff exactly"
        assert makefile_match.group("version") == project_match.group("version")
