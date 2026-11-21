"""Metric-style HTTP outcome events for the estate endpoints.

D27 deferred a telemetry platform, not the outcome events themselves. The
repository already emits metrics as structured log events a log aggregator can
count, so each estate request records exactly one event carrying only the
bounded labels ``operation``, ``outcome``, and ``status_class``.

The tests pin the vocabulary directly, then drive the real application so the
middleware wiring, including a request rejected before routing, is covered.
"""

import dataclasses
import types
import typing as typ

import falcon.asgi
import falcon.testing
import pytest

from ghillie.api.app import AppDependencies, create_app
from ghillie.api.estate.observability import (
    EstateOperation,
    EstateOutcome,
    EstateOutcomeMiddleware,
    classify_outcome,
    operation_for,
    record_http_outcome,
    status_class,
)
from ghillie.estate.errors import (
    InvalidPaginationError,
    StorageUnavailableError,
)
from tests.helpers.femtologging_capture import capture_femto_logs
from tests.unit.estate_test_helpers import (
    EmptyEstateManagement,
    FakeEstateManagement,
    build_estate_client,
)

if typ.TYPE_CHECKING:
    from ghillie.estate.models import EstateSummary, Page, PageRequest
    from ghillie.estate.ports import EstateManagement
    from tests.helpers.femtologging_capture import FemtoLogCapture

_LOGGER_NAME = "ghillie.api.estate.observability"
_STORAGE_MESSAGE = "storage is unavailable"
_PAGE_LIMIT_MESSAGE = "must be between 1 and 500"
_TOKEN = "s3cret-token-value"  # noqa: S105 - test credential, not a secret.
_EVENT_NAME = "estate.http.outcome"
_IMPORT_BODY = {
    "commit_sha": "c1",
    "estate_name": "Demo",
    "catalogue_yaml": "version: 1\n",
}


def _fields(message: str) -> dict[str, str]:
    """Parse a captured event line into its bounded label map."""
    parts = message.split()
    assert parts[0] == _EVENT_NAME, message
    fields: dict[str, str] = {}
    for part in parts[1:]:
        key, _, value = part.partition("=")
        fields[key] = value
    return fields


def _captured(logs: FemtoLogCapture) -> list[tuple[str, str]]:
    """Return ``(level, message)`` pairs once the capture has settled."""
    logs.wait_for_timeout()
    return [(record.level, record.message) for record in logs.records]


class _UnavailableEstateManagement(EmptyEstateManagement):
    """Port double whose estate listing fails at the storage boundary."""

    async def list_estates(self, page: PageRequest) -> Page[EstateSummary]:
        """Raise the storage failure that maps to a 503."""
        raise StorageUnavailableError(_STORAGE_MESSAGE)


class _InvalidPageEstateManagement(EmptyEstateManagement):
    """Port double whose estate listing rejects the page request."""

    async def list_estates(self, page: PageRequest) -> Page[EstateSummary]:
        """Raise the pagination failure that maps to a 400."""
        raise InvalidPaginationError("limit", _PAGE_LIMIT_MESSAGE)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (200, "2xx"),
        (204, "2xx"),
        (302, "3xx"),
        (400, "4xx"),
        (401, "4xx"),
        (422, "4xx"),
        (500, "5xx"),
        (503, "5xx"),
    ],
)
def test_status_class_reports_the_hundreds_band(code: int, expected: str) -> None:
    """The status class stays inside the hundred band of the status code."""
    assert status_class(code) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (200, EstateOutcome.SUCCEEDED),
        (204, EstateOutcome.SUCCEEDED),
        (302, EstateOutcome.FAILED),
        (400, EstateOutcome.REJECTED),
        (404, EstateOutcome.REJECTED),
        (503, EstateOutcome.FAILED),
    ],
)
def test_classify_outcome_partitions_success_rejection_and_failure(
    code: int, expected: EstateOutcome
) -> None:
    """2xx succeeds, 4xx is rejected, and everything else is a failure.

    A redirect counts as a failure because the estate API never issues one: an
    unexpected 3xx means the endpoint did not do the work the client asked for.
    """
    assert classify_outcome(code) is expected


def test_record_http_outcome_emits_one_bounded_event() -> None:
    """One event carries exactly the three bounded labels."""
    with capture_femto_logs(_LOGGER_NAME) as logs:
        record_http_outcome(EstateOperation.LIST_ESTATES, 200)
        captured = _captured(logs)

    assert len(captured) == 1, captured
    level, message = captured[0]
    assert level == "INFO", level
    assert _fields(message) == {
        "operation": "list_estates",
        "outcome": "succeeded",
        "status_class": "2xx",
    }, message


@pytest.mark.parametrize(
    ("code", "expected_levels"),
    [
        (404, {"WARN", "WARNING"}),
        (503, {"ERROR"}),
    ],
)
def test_record_http_outcome_logs_at_the_outcome_level(
    code: int, expected_levels: set[str]
) -> None:
    """A rejection is a warning and a failure is an error.

    The two spellings of warning are accepted because femtologging normalizes
    ``WARNING`` to ``WARN`` in some handlers.
    """
    with capture_femto_logs(_LOGGER_NAME) as logs:
        record_http_outcome(EstateOperation.IMPORT_CATALOGUE, code)
        captured = _captured(logs)

    assert len(captured) == 1, captured
    assert captured[0][0] in expected_levels, captured[0][0]


def test_operation_for_uses_the_route_template() -> None:
    """A routed request is attributed through its Falcon template."""
    assert (
        operation_for("/estates/{estate_key}/catalogue-import", "/ignored")
        is EstateOperation.IMPORT_CATALOGUE
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/estates", EstateOperation.LIST_ESTATES),
        (
            "/estates/demo/catalogue-import",
            EstateOperation.IMPORT_CATALOGUE,
        ),
        ("/estates/demo/registry-sync", EstateOperation.SYNC_REGISTRY),
        ("/estates/demo/repositories", EstateOperation.LIST_REPOSITORIES),
        (
            "/repositories/org/alpha/ingestion",
            EstateOperation.SET_INGESTION,
        ),
        ("//estates", EstateOperation.LIST_ESTATES),
        ("///estates/demo/registry-sync", EstateOperation.SYNC_REGISTRY),
    ],
)
def test_operation_for_falls_back_to_the_path_before_routing(
    path: str, expected: EstateOperation
) -> None:
    """A request rejected before routing is still attributed to its endpoint.

    Authentication runs before routing, so a 401 carries no URI template. Its
    path is matched against the same route shapes, which keeps the event count
    equal to the request count for the endpoint the client addressed.
    """
    assert operation_for(None, path) is expected


@pytest.mark.parametrize(
    ("template", "path"),
    [
        (None, "/health"),
        ("/health", "/health"),
        (None, "/estates/demo/catalogue-import/extra"),
        (None, "/estates/demo"),
    ],
)
def test_operation_for_ignores_other_paths(template: str | None, path: str) -> None:
    """Paths outside the five estate routes produce no operation."""
    assert operation_for(template, path) is None


@pytest.mark.parametrize(
    ("uri_template", "path", "expected_operation"),
    [
        ("/estates", "/estates", "list_estates"),
        ("/health", "/health", None),
    ],
    ids=["estate-route", "health-probe"],
)
@pytest.mark.asyncio
async def test_middleware_records_only_estate_routes(
    uri_template: str, path: str, expected_operation: str | None
) -> None:
    """The response hook attributes estate routes and ignores every other path.

    Falcon supplies a template once a request is routed, so a health probe has
    none of the five estate shapes and produces no event at all.
    """
    request = typ.cast(
        "falcon.asgi.Request",
        types.SimpleNamespace(uri_template=uri_template, path=path),
    )
    response = typ.cast("falcon.asgi.Response", types.SimpleNamespace(status_code=200))

    with capture_femto_logs(_LOGGER_NAME) as logs:
        await EstateOutcomeMiddleware().process_response(
            request, response, None, req_succeeded=True
        )
        captured = _captured(logs)

    if expected_operation is None:
        assert captured == [], captured
        return
    assert len(captured) == 1, captured
    assert _fields(captured[0][1])["operation"] == expected_operation


def test_each_estate_route_records_its_own_operation() -> None:
    """Every estate route records exactly one event naming its operation."""
    client = build_estate_client(FakeEstateManagement())

    with capture_femto_logs(_LOGGER_NAME) as logs:
        responses = [
            client.simulate_get("/estates"),
            client.simulate_post("/estates/demo/catalogue-import", json=_IMPORT_BODY),
            client.simulate_post("/estates/demo/registry-sync"),
            client.simulate_get("/estates/demo/repositories"),
            client.simulate_patch(
                "/repositories/org/alpha/ingestion",
                json={"ingestion_enabled": False},
            ),
        ]
        captured = _captured(logs)

    assert [response.status_code for response in responses] == [200] * 5, [
        response.text for response in responses
    ]
    assert len(captured) == 5, captured
    assert [_fields(message)["operation"] for _, message in captured] == [
        "list_estates",
        "import_catalogue",
        "sync_registry",
        "list_repositories",
        "set_ingestion",
    ], captured
    assert [_fields(message)["outcome"] for _, message in captured] == [
        "succeeded"
    ] * 5, captured


@dataclasses.dataclass(frozen=True, slots=True)
class _OutcomeCase:
    """One client-visible status the five estate routes must record."""

    service_type: typ.Callable[[], EstateManagement]
    expected_status: int
    expected_fields: dict[str, str]
    api_token: str | None = None
    path: str = "/estates"
    params: dict[str, str] | None = None
    authorize: bool = False


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _OutcomeCase(
                service_type=_InvalidPageEstateManagement,
                expected_status=400,
                expected_fields={
                    "operation": "list_estates",
                    "outcome": "rejected",
                    "status_class": "4xx",
                },
                params={"limit": "0"},
            ),
            id="rejected-400",
        ),
        pytest.param(
            _OutcomeCase(
                service_type=_UnavailableEstateManagement,
                expected_status=503,
                expected_fields={
                    "operation": "list_estates",
                    "outcome": "failed",
                    "status_class": "5xx",
                },
            ),
            id="failed-503",
        ),
        pytest.param(
            _OutcomeCase(
                service_type=FakeEstateManagement,
                expected_status=401,
                expected_fields={
                    "operation": "list_estates",
                    "outcome": "rejected",
                    "status_class": "4xx",
                },
                api_token=_TOKEN,
            ),
            id="unauthenticated-401",
        ),
        pytest.param(
            _OutcomeCase(
                service_type=FakeEstateManagement,
                expected_status=200,
                expected_fields={
                    "operation": "list_estates",
                    "outcome": "succeeded",
                    "status_class": "2xx",
                },
                api_token=_TOKEN,
                path="//estates",
                authorize=True,
            ),
            id="authenticated-doubled-slash",
        ),
        pytest.param(
            _OutcomeCase(
                service_type=FakeEstateManagement,
                expected_status=401,
                expected_fields={
                    "operation": "list_estates",
                    "outcome": "rejected",
                    "status_class": "4xx",
                },
                api_token=_TOKEN,
                path="//estates",
            ),
            id="unauthenticated-doubled-slash",
        ),
    ],
)
def test_estate_request_records_the_outcome_the_client_receives(
    case: _OutcomeCase,
) -> None:
    """Each client-visible status is recorded once against its endpoint.

    The cases cover a page request the endpoint rejects, a storage failure,
    and unauthenticated requests that are refused before routing: those still
    name the endpoint the client addressed, including when the path repeats its
    leading slash and only Falcon's own normalisation would have matched it.
    """
    client = falcon.testing.TestClient(
        create_app(
            AppDependencies(
                estate_service=case.service_type(), api_token=case.api_token
            )
        )
    )
    headers = {"Authorization": f"Bearer {_TOKEN}"} if case.authorize else None

    with capture_femto_logs(_LOGGER_NAME) as logs:
        response = client.simulate_get(case.path, params=case.params, headers=headers)
        captured = _captured(logs)

    assert response.status_code == case.expected_status, response.text
    assert len(captured) == 1, captured
    assert _fields(captured[0][1]) == case.expected_fields, captured
