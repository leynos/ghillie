"""Metric-style events for the estate HTTP endpoints (D27).

D27 deferred a telemetry platform, not the outcome events themselves. The
repository's existing convention, established by
``ghillie/github/observability.py`` and the D21 mutation records, is to emit
metrics as structured single-line log events a log aggregator can count. This
module applies that convention to the HTTP boundary: each estate request
records exactly one event carrying only bounded labels -- the operation, the
outcome, and the status class. Estate keys, repository names, commit SHAs, and
error strings never become labels, so the event's cardinality cannot grow with
the data.

Example:
-------
Count rejected catalogue imports over an hour::

    estate.http.outcome operation=import_catalogue outcome=rejected status_class=4xx

"""

from __future__ import annotations

import enum
import http
import re
import typing as typ

from ghillie.logging import get_logger, log_error, log_info, log_warning

if typ.TYPE_CHECKING:
    from falcon.asgi import Request, Response

logger = get_logger(__name__)

__all__ = [
    "EstateOperation",
    "EstateOutcome",
    "EstateOutcomeMiddleware",
    "classify_outcome",
    "operation_for",
    "record_http_outcome",
    "status_class",
]

_EVENT_TEMPLATE = "estate.http.outcome operation=%s outcome=%s status_class=%s"


class EstateOperation(enum.StrEnum):
    """The estate endpoint an event belongs to.

    The values are the ``EstateManagement`` port method names, so an operator
    can move from an event to the service method that served it without a
    second vocabulary.
    """

    LIST_ESTATES = "list_estates"
    IMPORT_CATALOGUE = "import_catalogue"
    SYNC_REGISTRY = "sync_registry"
    LIST_REPOSITORIES = "list_repositories"
    SET_INGESTION = "set_ingestion"


class EstateOutcome(enum.StrEnum):
    """How an estate request ended, in bounded terms."""

    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


# Keyed by the Falcon route templates registered in
# ``ghillie.api.app._register_estate_routes``; keep the two in step.
_ROUTE_OPERATIONS: dict[str, EstateOperation] = {
    "/estates": EstateOperation.LIST_ESTATES,
    "/estates/{estate_key}/catalogue-import": EstateOperation.IMPORT_CATALOGUE,
    "/estates/{estate_key}/registry-sync": EstateOperation.SYNC_REGISTRY,
    "/estates/{estate_key}/repositories": EstateOperation.LIST_REPOSITORIES,
    "/repositories/{owner}/{name}/ingestion": EstateOperation.SET_INGESTION,
}


def _path_pattern(template: str) -> re.Pattern[str]:
    """Compile a route template into an anchored path pattern.

    Each ``{field}`` matches exactly one path segment and the rest is literal,
    so the pattern cannot match a deeper or shallower path than the route.
    """
    segments = re.split(r"(\{[^}]+\})", template)
    pattern = "".join(
        "[^/]+" if segment.startswith("{") else re.escape(segment)
        for segment in segments
    )
    return re.compile(pattern + r"\Z")


_PATH_OPERATIONS: tuple[tuple[re.Pattern[str], EstateOperation], ...] = tuple(
    (_path_pattern(template), operation)
    for template, operation in _ROUTE_OPERATIONS.items()
)


def status_class(status_code: int) -> str:
    """Return the bounded class of *status_code*, such as ``"4xx"``.

    Parameters
    ----------
    status_code:
        HTTP status the response carries.

    Returns
    -------
    str
        The hundred band of the status code.

    """
    return f"{status_code // 100}xx"


def classify_outcome(status_code: int) -> EstateOutcome:
    """Map an HTTP status onto the outcome vocabulary.

    2xx is a success and 4xx is the client's request being rejected. Anything
    else is a failure: the estate API never redirects, so an unexpected 3xx, or
    a 5xx, means the endpoint did not do the work the client asked for.

    Parameters
    ----------
    status_code:
        HTTP status the response carries.

    Returns
    -------
    EstateOutcome
        The outcome to record for that status.

    """
    if http.HTTPStatus.OK <= status_code < http.HTTPStatus.MULTIPLE_CHOICES:
        return EstateOutcome.SUCCEEDED
    if (
        http.HTTPStatus.BAD_REQUEST
        <= status_code
        < http.HTTPStatus.INTERNAL_SERVER_ERROR
    ):
        return EstateOutcome.REJECTED
    return EstateOutcome.FAILED


def operation_for(
    uri_template: str | None,
    path: str,
) -> EstateOperation | None:
    """Return the estate operation a request belongs to, if any.

    ``uri_template`` is set by Falcon once routing picks a resource, so it is
    the cheaper lookup. A request rejected before routing -- an unauthenticated
    request, for example -- carries no template, so its path is matched against
    the same route shapes instead. That keeps the event count equal to the
    request count for the endpoint the client addressed.

    Falcon collapses repeated leading slashes before it matches routes, so
    ``//estates`` is served by the estate list route. A request refused before
    routing never reaches that step, so the same collapse is applied here; the
    fallback then attributes both forms to one operation.

    Parameters
    ----------
    uri_template:
        Route template Falcon matched, or ``None`` when routing never ran.
    path:
        Request path, read only when no template was matched.

    Returns
    -------
    EstateOperation | None
        The endpoint the request targeted, or ``None`` for any other path.

    """
    if uri_template is not None:
        return _ROUTE_OPERATIONS.get(uri_template)
    routed_path = "/" + path.lstrip("/")
    for pattern, operation in _PATH_OPERATIONS:
        if pattern.match(routed_path):
            return operation
    return None


def record_http_outcome(operation: EstateOperation, status_code: int) -> None:
    """Emit the one metric-style event for a finished estate request.

    The event is logged at the level of its outcome: a success at INFO, a
    rejection at WARNING, and a failure at ERROR. Wording is static because
    every variable part is already a bounded field; a client-supplied string
    never reaches the line.

    Parameters
    ----------
    operation:
        Endpoint the request targeted.
    status_code:
        HTTP status the response carried.

    """
    outcome = classify_outcome(status_code)
    fields = (operation, outcome, status_class(status_code))
    if outcome is EstateOutcome.SUCCEEDED:
        log_info(logger, _EVENT_TEMPLATE, *fields)
    elif outcome is EstateOutcome.REJECTED:
        log_warning(logger, _EVENT_TEMPLATE, *fields)
    else:
        log_error(logger, _EVENT_TEMPLATE, *fields)


class EstateOutcomeMiddleware:
    """Record one metric-style event per estate HTTP outcome.

    Falcon runs ``process_response`` for every response, including one an
    earlier ``process_request`` produced by raising, so a request rejected
    before routing is counted too. The application registers this component
    first in the middleware list so its hook runs last: by then the session
    middleware has committed or rolled back, and the status is the one the
    client actually receives.

    Non-estate routes, such as the health probes, are ignored.
    """

    async def process_response(
        self,
        req: Request,
        resp: Response,
        resource: object,
        req_succeeded: bool,  # noqa: FBT001 - Falcon middleware signature.
    ) -> None:
        """Record the request's outcome when it targeted an estate route.

        Parameters
        ----------
        req:
            Request that produced the response.
        resp:
            Response whose status is recorded.
        resource:
            Routed resource, unused.
        req_succeeded:
            Whether Falcon considered the request successful, unused.

        """
        operation = operation_for(req.uri_template, req.path)
        if operation is None:
            return
        record_http_outcome(operation, resp.status_code)
