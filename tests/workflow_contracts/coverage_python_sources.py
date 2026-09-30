"""Read which Python each generate-coverage call measures on.

Support for ``test_coverage_python_version.py``: the resolver's source order,
the reading of every call's declared sources, the verdict on whether they
agree, and the version comparison. It knows nothing about this repository's
lanes; the tests apply it to them.
"""

from __future__ import annotations

import tomllib
import typing as typ
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .loading import WorkflowReadingError, load_workflow

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
#: The pull-request lane and the publisher whose baseline it ratchets against.
LANES: typ.Final[tuple[str, ...]] = ("ci.yml", "coverage-main.yml")
SETUP_PYTHON: typ.Final[str] = "actions/setup-python@"
GENERATE_COVERAGE: typ.Final[str] = "/.github/actions/generate-coverage@"
#: The resolver's order, highest priority first.
SOURCES: typ.Final[tuple[str, ...]] = (
    "input",
    "UV_PYTHON",
    ".python-version",
    "setup-python",
)


class CoverageContractError(Exception):
    """Raised when a file the contract reads cannot be read or is the wrong shape.

    The message names the file or level, so a failing contract says which input
    was at fault rather than judging nothing.
    """


class CoverageCall(typ.NamedTuple):
    """One generate-coverage call and the versions each source declares for it.

    Parameters
    ----------
    job : str
        The name of the job that contains the call.
    sources : dict[str, str]
        The version each resolver source declares, in priority order, with an
        empty string where a source declares nothing.

    """

    job: str
    sources: dict[str, str]

    @property
    def declared(self) -> dict[str, str]:
        """The sources that name a version."""
        return {name: version for name, version in self.sources.items() if version}

    @property
    def effective(self) -> str:
        """The version the resolver would choose, or empty."""
        return next(iter(self.declared.values()), "")


def verdict(call: CoverageCall) -> str:
    """Return why a call's declared sources fail the contract, or empty.

    ``"undeclared"`` means no source names a version, so the call would
    measure on whatever Python the runner happens to have; ``"conflicting"``
    means two sources name different versions, so a higher-priority value
    silently overrides a lower one.

    Parameters
    ----------
    call : CoverageCall
        The call to judge.

    Returns
    -------
    str
        ``"undeclared"``, ``"conflicting"``, or ``""`` when every declared
        source agrees.

    """
    declared = set(call.declared.values())
    if not declared:
        return "undeclared"
    return "conflicting" if len(declared) > 1 else ""


def requires_python(pyproject: str) -> SpecifierSet:
    """Return the project's ``requires-python`` specifier set.

    Parameters
    ----------
    pyproject : str
        The text of ``pyproject.toml``.

    Returns
    -------
    SpecifierSet
        The versions the project declares it accepts.

    Raises
    ------
    CoverageContractError
        If the text is not TOML, has no ``project.requires-python`` string, or
        that string is not a version specifier; the original error is the cause.

    """
    try:
        value = tomllib.loads(pyproject)["project"]["requires-python"]
    except (tomllib.TOMLDecodeError, KeyError, TypeError) as error:
        message = f"pyproject.toml has no usable project.requires-python: {error!r}"
        raise CoverageContractError(message) from error
    if not isinstance(value, str):
        # SpecifierSet also takes an iterable, so `[]` or `{}` would build an
        # unrestricted set and accept every version.
        message = f"requires-python must be a string, not {type(value).__name__}"
        raise CoverageContractError(message)
    try:
        return SpecifierSet(value)
    except InvalidSpecifier as error:
        message = f"requires-python is not a version specifier: {error}"
        raise CoverageContractError(message) from error


def read_required_text(path: Path) -> str:
    """Return the text of a file the contract cannot run without.

    Parameters
    ----------
    path : Path
        The file to read.

    Returns
    -------
    str
        The file's UTF-8 text.

    Raises
    ------
    CoverageContractError
        If the file is missing, unreadable or not valid UTF-8; the message
        names the path and the ``OSError`` or ``UnicodeDecodeError`` is the
        cause.

    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        message = f"{path} could not be read: {error}"
        raise CoverageContractError(message) from error


def read_text_if_present(path: Path) -> str | None:
    """Return a file's text, or ``None`` when the file does not exist.

    Only a missing file reads as absent: a directory, a permission failure or
    undecodable bytes raise :class:`CoverageContractError`, which fails the
    contract loudly rather than reading as absent.

    Parameters
    ----------
    path : Path
        The file to read.

    Returns
    -------
    str or None
        The file's text, or ``None`` when it is absent.

    Raises
    ------
    CoverageContractError
        If the file exists but cannot be read.

    """
    try:
        return read_required_text(path)
    except CoverageContractError as error:
        if isinstance(error.__cause__, FileNotFoundError):
            return None
        raise


def python_version_entry(text: str | None) -> str:
    """Return the first non-comment entry of ``.python-version`` text, or empty.

    Pure: the caller reads the file (see :func:`read_text_if_present`), so the
    parsing is tested on text alone. ``None`` means the file is absent.

    Parameters
    ----------
    text : str or None
        The file's text, or ``None`` when the file is absent.

    Returns
    -------
    str
        The first entry that is not blank or a comment, or ``""``.

    """
    entries = (line.strip() for line in (text or "").splitlines())
    return next((entry for entry in entries if entry and not entry.startswith("#")), "")


def _required_mapping(value: object, what: str) -> dict[str, object]:
    """Return ``value`` as a mapping.

    Raises
    ------
    CoverageContractError
        If ``value`` is not a mapping, ``None`` included, naming ``what``. A key
        that is absent is the caller's to skip; a key that is present must hold
        a mapping.

    """
    if not isinstance(value, dict):
        message = f"{what} must be a mapping, not {type(value).__name__}"
        raise CoverageContractError(message)
    return typ.cast("dict[str, object]", value)


def _optional_mapping(
    scope: dict[str, object], key: str, what: str
) -> dict[str, object]:
    """Return ``scope[key]`` as a mapping, or an empty one when the key is absent.

    Raises
    ------
    CoverageContractError
        If the key is present but not a mapping, null included, naming ``what``.

    """
    return _required_mapping(scope[key], what) if key in scope else {}


def _steps_of(job: dict[str, object], name: str) -> list[dict[str, object]]:
    """Return a job's steps in order, or none when it declares no ``steps`` key.

    Raises
    ------
    CoverageContractError
        If ``steps`` is present but not a list, or an item is not a mapping.

    """
    if "steps" not in job:
        return []
    steps = job["steps"]
    if not isinstance(steps, list):
        message = f"steps of job {name} must be a list, not {type(steps).__name__}"
        raise CoverageContractError(message)
    return [
        _required_mapping(step, f"step {index} of job {name}")
        for index, step in enumerate(steps)
    ]


def _declared_by_setup(step: dict[str, object]) -> str:
    """Return the version a setup-python step reliably puts on ``PATH``, or empty."""
    if "if" in step or step.get("continue-on-error"):
        return ""
    with_ = _optional_mapping(step, "with", "with of a setup-python step")
    return str(with_.get("python-version") or "")


def _uv_python(*scopes: dict[str, object]) -> str:
    """Return the innermost ``UV_PYTHON`` among step, job and workflow scopes.

    The first scope that defines the key wins even when its value is empty: an
    empty step value replaces the outer one, and the action then falls through
    to ``.python-version`` or ``PATH`` rather than to the outer value.
    """
    for scope in scopes:
        env = _optional_mapping(scope, "env", "env")
        if "UV_PYTHON" in env:
            return str(env["UV_PYTHON"] or "")
    return ""


def _job_calls(
    name: str, job: dict[str, object], document: dict[str, object], python_version: str
) -> list[CoverageCall]:
    """Return one job's coverage calls, reading its steps in order."""
    calls: list[CoverageCall] = []
    on_path = ""
    for step in _steps_of(job, name):
        uses = str(step.get("uses", ""))
        if uses.startswith(SETUP_PYTHON):
            on_path = _declared_by_setup(step)
        elif GENERATE_COVERAGE in uses:
            inputs = _optional_mapping(step, "with", "with of a coverage step")
            versions = (
                str(inputs.get("python-version") or ""),
                _uv_python(step, job, document),
                python_version,
                on_path,
            )
            calls.append(CoverageCall(name, dict(zip(SOURCES, versions, strict=True))))
    return calls


def coverage_calls(workflow: str, python_version: str = "") -> list[CoverageCall]:
    """Return every generate-coverage call in a workflow with its declared sources.

    Each job's steps are read in order. A setup-python step that always runs
    replaces the Python on ``PATH`` for the steps after it; one that may be
    skipped or fail green clears it, since the call cannot rely on it.

    Parameters
    ----------
    workflow : str
        The text of one workflow file.
    python_version : str
        The repository's ``.python-version`` entry, or empty.

    Returns
    -------
    list of CoverageCall
        One entry per call, in workflow order, with every source's version in
        the resolver's priority order (empty where a source declares nothing).

    Raises
    ------
    CoverageContractError
        If the text is not YAML, repeats a mapping key, or the workflow, a
        present ``jobs``, a job, a present ``steps`` or a step, or the ``env``
        and ``with`` a coverage or setup step reads, is not the mapping or list
        it must be (null included), so a wrongly shaped file fails rather than
        reading as empty.

    """
    try:
        document = _required_mapping(load_workflow(workflow), "a workflow")
    except WorkflowReadingError as error:
        raise CoverageContractError(str(error)) from error
    jobs = _required_mapping(document["jobs"], "jobs") if "jobs" in document else {}
    return [
        call
        for name, job in jobs.items()
        for call in _job_calls(
            name, _required_mapping(job, f"job {name}"), document, python_version
        )
    ]


def rejected_versions(accepted: SpecifierSet, requested: list[str]) -> list[str]:
    """Return the requested versions the specifier set does not accept.

    Parameters
    ----------
    accepted : SpecifierSet
        The project's ``requires-python``.
    requested : list of str
        Versions to check.

    Returns
    -------
    list of str
        The requested versions outside ``accepted``, in their original order.

    Raises
    ------
    CoverageContractError
        If a requested version is not a valid version string.

    """
    try:
        return [version for version in requested if Version(version) not in accepted]
    except InvalidVersion as error:
        message = f"not a version: {error}"
        raise CoverageContractError(message) from error
