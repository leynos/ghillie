"""Behavioural scenarios for estate management through the CLI and API.

One scenario fixture owns an :class:`asyncio.Runner`. The Falcon app, its
SQLAlchemy engine, and its async client all live on that loop;
:class:`RunnerTransport` hops each synchronous CLI request onto it, so database
sessions never cross loops.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import functools
import io
import json
import re
import shlex
import typing as typ
from pathlib import Path

import httpx
import pytest
from pytest_bdd import given, parsers, scenario, then, when
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from ghillie.api.app import AppDependencies, create_app
from ghillie.cli import control_plane, main
from ghillie.estate.service import EstateManagementService
from ghillie.registry.service import RepositoryRegistryService
from ghillie.storage_bootstrap import init_all_storage
from tests.helpers.runner_transport import RunnerTransport

REPO_ROOT = Path(__file__).resolve().parents[3]
WILDSIDE_CATALOGUE = "examples/wildside-catalogue.yaml"

_CLI_ENVIRONMENT = (
    "GHILLIE_API_BASE_URL",
    "GHILLIE_API_TOKEN",
    "GHILLIE_AUTH_TOKEN",
    "GHILLIE_DRY_RUN",
    "GHILLIE_LOG_LEVEL",
    "GHILLIE_NON_INTERACTIVE",
    "GHILLIE_OUTPUT",
    "GHILLIE_REQUEST_TIMEOUT_S",
)

_CREATED_RE = re.compile(r"^repositories\.created: (\d+)$", re.MULTILINE)


@dataclasses.dataclass
class ScenarioState:
    """Mutable state shared between the steps of one scenario.

    Attributes
    ----------
    transport
        The in-process transport, which also records every request.
    exit_code
        Exit code of the most recent CLI invocation.
    stdout
        Standard output of the most recent CLI invocation.
    stderr
        Standard error of the most recent CLI invocation.
    last_document
        Parsed JSON of the most recent command run with JSON output.
    last_sync_document
        Parsed JSON of the most recent sync, kept apart from later commands.
    catalogue_path
        Ad hoc catalogue file created by a ``Given`` step.

    """

    transport: RunnerTransport
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    last_document: dict[str, object] = dataclasses.field(default_factory=dict)
    last_sync_document: dict[str, object] = dataclasses.field(default_factory=dict)
    catalogue_path: Path | None = None


# ---------------------------------------------------------------------------
# Scenario wrappers
# ---------------------------------------------------------------------------


@scenario(
    "../estate_management.feature",
    "Operator imports a catalogue for a new estate",
)
def test_operator_imports_a_catalogue_for_a_new_estate() -> None:
    """Import a catalogue and find the estate afterwards."""


@scenario(
    "../estate_management.feature",
    "Re-importing the same commit is skipped",
)
def test_reimporting_the_same_commit_is_skipped() -> None:
    """A repeated commit reports ``skipped`` instead of importing twice."""


@scenario(
    "../estate_management.feature",
    "A dry-run import changes nothing",
)
def test_a_dry_run_import_changes_nothing() -> None:
    """A dry run leaves the estate list empty."""


@scenario(
    "../estate_management.feature",
    "Operator syncs the registry and lists repositories",
)
def test_operator_syncs_the_registry_and_lists_repositories() -> None:
    """Sync projects the catalogue repositories into the registry."""


@scenario(
    "../estate_management.feature",
    "Operator disables ingestion and it survives a re-sync",
)
def test_operator_disable_survives_a_resync() -> None:
    """An operator toggle outlives a later catalogue import and sync."""


@scenario(
    "../estate_management.feature",
    "Syncing an unknown estate fails with a structured error",
)
def test_syncing_an_unknown_estate_fails() -> None:
    """An unknown estate is a structured 404 with an actionable hint."""


@scenario(
    "../estate_management.feature",
    "Importing an invalid catalogue is rejected",
)
def test_importing_an_invalid_catalogue_is_rejected() -> None:
    """A schema-invalid catalogue is rejected by the service."""


@scenario(
    "../estate_management.feature",
    "Toggling an unknown repository fails",
)
def test_toggling_an_unknown_repository_fails() -> None:
    """An unknown repository is a structured 404."""


@scenario(
    "../estate_management.feature",
    "Invalid pagination is rejected before any request",
)
def test_invalid_pagination_is_rejected_locally() -> None:
    """Cyclopts rejects an out-of-range limit without a request."""


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


def _build_engine(tmp_path: Path) -> AsyncEngine:
    """Build a file-backed SQLite engine sharing one connection.

    A static pool keeps every session on the connection the runner's loop
    created, which is the SQLite analogue of py-pglite's ``NullPool`` setup.
    """
    return create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'ghillie.db'}",
        poolclass=StaticPool,
    )


@pytest.fixture
def estate_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> typ.Iterator[ScenarioState]:
    """Build an in-process service and app, then hop the CLI onto its loop."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in _CLI_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)

    runner = asyncio.Runner()
    engine = _build_engine(tmp_path)
    runner.run(init_all_storage(engine))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    registry = RepositoryRegistryService(session_factory, session_factory)
    service = EstateManagementService(session_factory, registry=registry)
    app = create_app(AppDependencies(estate_service=service))
    async_client = httpx.AsyncClient(
        # Falcon types the scope as a MutableMapping; the ASGI transport
        # annotates the narrower ``dict`` and accepts the app at runtime.
        transport=httpx.ASGITransport(app=typ.cast("typ.Any", app)),
        base_url="http://ghillie.test",
    )
    transport = RunnerTransport(runner, async_client)

    real_client = httpx.Client
    monkeypatch.setattr(
        control_plane.httpx,
        "Client",
        functools.partial(real_client, transport=transport),
    )

    state = ScenarioState(transport=transport)
    try:
        yield state
    finally:
        runner.run(async_client.aclose())
        runner.run(engine.dispose())
        runner.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_argv(state: ScenarioState, argv: typ.Sequence[str]) -> None:
    """Invoke the CLI with *argv*, capturing its exit code and streams."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        state.exit_code = main(list(argv))
    state.stdout = stdout.getvalue()
    state.stderr = stderr.getvalue()
    state.last_document = _maybe_document(state.stdout)


def _run(state: ScenarioState, arguments: str) -> None:
    """Invoke the CLI with a shell-like *arguments* string."""
    _run_argv(state, shlex.split(arguments))


def _maybe_document(output: str) -> dict[str, object]:
    """Parse JSON output when the command produced it."""
    try:
        parsed = json.loads(output)
    except ValueError:
        return {}
    return typ.cast("dict[str, object]", parsed) if isinstance(parsed, dict) else {}


@dataclasses.dataclass(frozen=True, slots=True)
class _ImportSpec:
    """One catalogue import as a scenario step asks for it."""

    catalogue: str | Path
    estate_key: str
    commit_sha: str
    dry_run: bool = False
    output: str | None = None


def _import(state: ScenarioState, spec: _ImportSpec) -> None:
    """Import the catalogue described by *spec*."""
    path = Path(spec.catalogue)
    if not path.is_absolute():
        path = REPO_ROOT / path
    argv: list[str] = []
    if spec.output is not None:
        argv += ["--output", spec.output]
    if spec.dry_run:
        argv.append("--dry-run")
    argv += [
        "estate",
        "import",
        "--estate-key",
        spec.estate_key,
        "--catalogue-path",
        str(path),
        "--commit-sha",
        spec.commit_sha,
    ]
    _run_argv(state, argv)


def _sync(state: ScenarioState, estate_key: str, *, output: str | None = None) -> None:
    """Sync *estate_key*, optionally asking for JSON output."""
    argv: list[str] = []
    if output is not None:
        argv += ["--output", output]
    argv += ["estate", "sync", "--estate-key", estate_key]
    _run_argv(state, argv)
    if output == "json":
        # Keep the sync document: a later list command replaces ``last_document``.
        state.last_sync_document = state.last_document


_STDERR_LABELS = {"Code": "code", "Hint": "hint"}


def _labelled_field(line: str) -> tuple[str, str] | None:
    """Return the ``(name, value)`` of one labelled error line, if it is one."""
    label, separator, value = line.partition(": ")
    name = _STDERR_LABELS.get(label)
    if not separator or name is None:
        return None
    return name, value


def _labelled_error_fields(output: str) -> dict[str, object]:
    """Read the error code and hint from table-mode labelled lines."""
    fields: dict[str, object] = {}
    for line in output.splitlines():
        pair = _labelled_field(line)
        if pair is not None:
            fields[pair[0]] = pair[1]
    return fields


def _json_error(output: str) -> dict[str, object] | None:
    """Return the documented ``error`` object of *output*, if it has one."""
    try:
        parsed = json.loads(output)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    error = parsed.get("error")
    return typ.cast("dict[str, object]", error) if isinstance(error, dict) else None


_IMPORT_PHRASE = (
    'the operator imports "{catalogue}" into estate "{estate_key}" '
    'at commit "{commit_sha}"'
)
"""The step phrase shared by imports that differ only in CLI options."""


class _StepRegister(typ.Protocol):
    """A pytest-bdd ``given``/``when`` decorator factory.

    Both factories hand back the step function unchanged, so the protocol
    describes only the registration call these helpers make.
    """

    def __call__(
        self,
        name: str | parsers.StepParser,
        *,
        stacklevel: int = ...,
    ) -> typ.Callable[[typ.Callable[..., None]], typ.Callable[..., None]]: ...


class _ImportStepOptions(typ.NamedTuple):
    """Options an import step phrase contributes to its CLI invocation."""

    dry_run: bool = False
    output: str | None = None
    assert_success: bool = False


def _register_import(
    register: _StepRegister,
    phrase: str,
    options: _ImportStepOptions | None = None,
) -> None:
    """Register an import step whose phrase selects the CLI options."""
    resolved = options or _ImportStepOptions()

    # ``stacklevel=2`` makes pytest-bdd register the synthetic step fixture in
    # this module's namespace rather than in this factory's local frame.
    @register(parsers.parse(phrase), stacklevel=2)
    def step(
        estate_state: ScenarioState,
        catalogue: str,
        estate_key: str,
        commit_sha: str,
    ) -> None:
        _import(
            estate_state,
            _ImportSpec(
                catalogue,
                estate_key,
                commit_sha,
                dry_run=resolved.dry_run,
                output=resolved.output,
            ),
        )
        if resolved.assert_success:
            assert estate_state.exit_code == 0, estate_state.stderr


def _register_import_and_sync(
    register: _StepRegister,
    phrase: str,
) -> None:
    """Register a step that imports the wildside catalogue and syncs it."""

    @register(parsers.parse(phrase), stacklevel=2)
    def step(estate_state: ScenarioState, estate_key: str, commit_sha: str) -> None:
        _import(
            estate_state,
            _ImportSpec(WILDSIDE_CATALOGUE, estate_key, commit_sha, output="json"),
        )
        assert estate_state.exit_code == 0, estate_state.stderr
        _sync(estate_state, estate_key, output="json")
        assert estate_state.exit_code == 0, estate_state.stderr


def _error_fields(state: ScenarioState) -> dict[str, object]:
    """Read the error code and hint from JSON or table output.

    Machine-readable modes write the documented envelope; table mode writes
    labelled lines. Both carry the same stable code, so the assertions work
    whichever format the scenario asked for.
    """
    error = _json_error(state.stderr)
    if error is not None:
        return error
    fields = _labelled_error_fields(state.stderr)
    assert fields, f"no error output: {state.stderr!r}"
    return fields


def _repository_items(state: ScenarioState, command: str) -> list[dict[str, object]]:
    """Run a repository list command with JSON output and return its items."""
    _run_argv(state, ["--output", "json", *shlex.split(command)])
    assert state.exit_code == 0, f"listing failed: {state.stderr}"
    items = state.last_document.get("items")
    assert isinstance(items, list), f"expected items, got {state.last_document!r}"
    return [typ.cast("dict[str, object]", item) for item in items]


def _assert_lists_repository(
    state: ScenarioState,
    command: str,
    reference: str,
) -> None:
    """Assert *command* lists the ``owner/name`` *reference*."""
    owner, name = reference.split("/", maxsplit=1)
    items = _repository_items(state, command)
    assert any(
        item.get("owner") == owner and item.get("name") == name for item in items
    ), f"expected {reference} in {items!r}"


# ---------------------------------------------------------------------------
# Given steps
# ---------------------------------------------------------------------------


@given("a Ghillie service backed by an empty database")
def given_an_empty_service(estate_state: ScenarioState) -> None:
    """Confirm the scenario fixture built the empty in-process service."""
    assert estate_state.transport.requests == [], "expected a fresh transport"


_register_import(
    given,
    'the operator has imported "{catalogue}" into estate "{estate_key}" '
    'at commit "{commit_sha}"',
    _ImportStepOptions(assert_success=True),
)
_register_import_and_sync(
    given,
    'estate "{estate_key}" has been imported at commit "{commit_sha}" and synced',
)


@given(parsers.parse('a catalogue file containing "{document}"'))
def given_a_catalogue_file(
    estate_state: ScenarioState,
    tmp_path: Path,
    document: str,
) -> None:
    """Write an ad hoc catalogue document for the next import."""
    path = tmp_path / "catalogue.yaml"
    path.write_text(f"version: 1\n{document}\n", encoding="utf-8")
    estate_state.catalogue_path = path


# ---------------------------------------------------------------------------
# When steps
# ---------------------------------------------------------------------------


_register_import(when, _IMPORT_PHRASE)
_register_import(
    when,
    f"{_IMPORT_PHRASE} with JSON output",
    _ImportStepOptions(output="json"),
)
_register_import(
    when,
    'the operator dry-run imports "{catalogue}" into estate "{estate_key}" '
    'at commit "{commit_sha}"',
    _ImportStepOptions(dry_run=True),
)


@when(
    parsers.parse(
        'the operator imports that file into estate "{estate_key}" '
        'at commit "{commit_sha}"'
    )
)
def when_the_operator_imports_that_file(
    estate_state: ScenarioState,
    estate_key: str,
    commit_sha: str,
) -> None:
    """Import the catalogue file created by the ``Given`` step."""
    path = estate_state.catalogue_path
    assert path is not None, "no ad hoc catalogue file was created"
    _import(estate_state, _ImportSpec(path, estate_key, commit_sha))


_register_import_and_sync(
    when,
    'the operator imports estate "{estate_key}" at commit "{commit_sha}" and syncs it',
)


@when(parsers.parse('the operator runs "{arguments}"'))
def when_the_operator_runs(estate_state: ScenarioState, arguments: str) -> None:
    """Run an arbitrary CLI command."""
    _run(estate_state, arguments)


# ---------------------------------------------------------------------------
# Then steps
# ---------------------------------------------------------------------------


@then(parsers.parse("the command exits with code {expected:d}"))
def then_the_command_exits(estate_state: ScenarioState, expected: int) -> None:
    """Assert the exit code."""
    assert estate_state.exit_code == expected, (
        f"expected exit {expected}, got {estate_state.exit_code}: "
        f"{estate_state.stderr or estate_state.stdout}"
    )


@then(parsers.parse("the output reports at least {minimum:d} repository created"))
def then_the_output_reports_repositories(
    estate_state: ScenarioState,
    minimum: int,
) -> None:
    """Assert the import summary counts at least *minimum* repositories."""
    matches = _CREATED_RE.findall(estate_state.stdout)
    assert matches, f"no repository count in output: {estate_state.stdout!r}"
    assert int(matches[-1]) >= minimum, (
        f"expected at least {minimum} repositories created, got {matches[-1]}"
    )


@then(parsers.parse('the JSON output field "{field}" is true'))
def then_the_json_field_is_true(estate_state: ScenarioState, field: str) -> None:
    """Assert a JSON response field is exactly ``true``."""
    document = _maybe_document(estate_state.stdout)
    assert document.get(field) is True, f"expected {field} true in {document!r}"


@then(parsers.parse('the JSON output field "{field}" is "{value}"'))
def then_the_json_field_is(
    estate_state: ScenarioState,
    field: str,
    value: str,
) -> None:
    """Assert a JSON response field equals *value*."""
    document = _maybe_document(estate_state.stdout)
    assert document.get(field) == value, f"expected {field}={value!r} in {document!r}"


@then(parsers.parse('"estate list" lists the estate "{estate_key}"'))
def then_estate_list_lists_estate(
    estate_state: ScenarioState,
    estate_key: str,
) -> None:
    """Assert the estate table has a row for *estate_key*."""
    _run(estate_state, "estate list")
    assert estate_state.exit_code == 0, estate_state.stderr
    assert re.search(
        rf"^{re.escape(estate_key)}(\s|$)",
        estate_state.stdout,
        flags=re.MULTILINE,
    ), f"expected {estate_key} in {estate_state.stdout!r}"


@then('"estate list" lists no estates')
def then_estate_list_is_empty(estate_state: ScenarioState) -> None:
    """Assert the estate table is empty."""
    _run(estate_state, "estate list")
    assert estate_state.exit_code == 0, estate_state.stderr
    assert "(no items)" in estate_state.stdout, estate_state.stdout


@then(parsers.parse('"{command}" lists "{reference}"'))
def then_the_command_lists_repository(
    estate_state: ScenarioState,
    command: str,
    reference: str,
) -> None:
    """Assert a repository list command shows ``owner/name``."""
    _assert_lists_repository(estate_state, command, reference)


@then(parsers.parse('the last sync reported "{reference}" as left disabled'))
def then_the_last_sync_reported_left_disabled(
    estate_state: ScenarioState,
    reference: str,
) -> None:
    """Assert the last sync document names *reference* as left disabled."""
    document = estate_state.last_sync_document
    left_disabled = document.get("repositories_left_disabled")
    assert isinstance(left_disabled, list), (
        f"expected a sync document, got {document!r}"
    )
    assert reference in left_disabled, (
        f"expected {reference} left disabled, got {left_disabled!r}"
    )


@then(parsers.parse('the error code is "{expected}"'))
def then_the_error_code_is(estate_state: ScenarioState, expected: str) -> None:
    """Assert the CLI error envelope carries *expected*."""
    error = _error_fields(estate_state)
    assert error.get("code") == expected, f"expected code {expected}, got {error!r}"


@then(parsers.parse('the error hint mentions "{fragment}"'))
def then_the_error_hint_mentions(
    estate_state: ScenarioState,
    fragment: str,
) -> None:
    """Assert the CLI error hint names *fragment*."""
    error = _error_fields(estate_state)
    hint = error.get("hint")
    assert isinstance(hint, str), f"expected a hint, got {hint!r}"
    assert fragment in hint, f"expected {fragment!r} in hint, got {hint!r}"


@then("no HTTP request was sent")
def then_no_http_request_was_sent(estate_state: ScenarioState) -> None:
    """Assert local validation stopped the command before any request."""
    assert estate_state.transport.requests == [], (
        f"unexpected requests: {estate_state.transport.requests!r}"
    )
