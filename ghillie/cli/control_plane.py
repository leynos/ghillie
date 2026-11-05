"""HTTP control-plane client helpers for the operator CLI."""

from __future__ import annotations

import dataclasses
import json
import typing as typ
from urllib.parse import quote

import httpx

if typ.TYPE_CHECKING:
    import http

    from .config import ResolvedCliConfig

_HTTP_ERROR_FALLBACK = "the control plane returned an error"
_HTTP_ERROR_THRESHOLD = 400


@dataclasses.dataclass(frozen=True, slots=True)
class ControlPlaneIssue:
    """One machine-readable issue inside a rejected request."""

    code: str
    message: str


class ControlPlaneError(Exception):
    """A control-plane call failed in a way the operator must see.

    Attributes
    ----------
    code:
        Stable machine-readable code, from the server when it supplies one.
    message:
        Human-readable description safe to print.
    hint:
        Suggested next action, filled in by the command layer.
    status:
        HTTP status, or ``None`` for a transport or local failure.
    issues:
        Per-field or per-item issues attached to a rejected request.

    """

    # Cyclopts-independent keyword options make the failure self-describing.
    def __init__(  # noqa: PLR0913
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        status: int | None = None,
        issues: typ.Iterable[ControlPlaneIssue] = (),
    ) -> None:
        """Capture one failure without leaking transport or credential detail."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.status = status
        self.issues = tuple(issues)


class ControlPlaneHTTPError(ControlPlaneError):
    """The service answered with a non-2xx status."""


class ControlPlaneTransportError(ControlPlaneError):
    """The request never produced a response."""


class ControlPlaneTimeoutError(ControlPlaneError):
    """The request exceeded the configured timeout."""


def encode_json_body(payload: typ.Mapping[str, object]) -> bytes:
    """Serialize *payload* once to the exact bytes put on the wire.

    ``ensure_ascii=False`` keeps multibyte characters as UTF-8, so the returned
    length is the byte length the server measures (O5) rather than a character
    count that would quietly diverge for non-ASCII catalogues.
    """
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _json_object(response: httpx.Response) -> dict[str, object] | None:
    """Decode a JSON object leniently, returning ``None`` for anything else."""
    try:
        payload = json.loads(response.content)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _text(value: object) -> str | None:
    """Return *value* when it is a non-empty string."""
    return value if isinstance(value, str) and value else None


def _issues_from(payload: typ.Mapping[str, object]) -> tuple[ControlPlaneIssue, ...]:
    """Read the documented ``issues`` list, ignoring malformed entries."""
    raw = payload.get("issues")
    if not isinstance(raw, list):
        return ()
    issues: list[ControlPlaneIssue] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = _text(item.get("code"))
        message = _text(item.get("message"))
        if code is not None and message is not None:
            issues.append(ControlPlaneIssue(code, message))
    return tuple(issues)


def _http_error(response: httpx.Response) -> ControlPlaneHTTPError:
    """Build the structured error for a non-2xx response (D7)."""
    payload = _json_object(response)
    code = f"http_{response.status_code}"
    message = response.reason_phrase or _HTTP_ERROR_FALLBACK
    issues: tuple[ControlPlaneIssue, ...] = ()
    if payload is not None:
        code = _text(payload.get("code")) or code
        message = (
            _text(payload.get("description")) or _text(payload.get("title")) or message
        )
        issues = _issues_from(payload)
    return ControlPlaneHTTPError(
        code,
        message,
        status=response.status_code,
        issues=issues,
    )


def _success_document(response: httpx.Response) -> dict[str, object]:
    """Return the JSON object of a successful response.

    Raises
    ------
    ControlPlaneError
        If a successful response is not a JSON object.

    """
    payload = _json_object(response)
    if payload is None:
        message = "the control plane returned a response that is not a JSON object"
        raise ControlPlaneError("invalid_response", message)
    return payload


class ControlPlaneClient:
    """Thin `httpx` wrapper configured from resolved CLI settings.

    Note:
        When a custom ``http_client`` is provided, it is used directly and
        must include the necessary ``User-Agent`` and ``Authorization`` headers.
        Callers are responsible for ensuring custom clients are properly configured.

    """

    def __init__(
        self,
        config: ResolvedCliConfig,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Build a control-plane client from resolved CLI configuration.

        Parameters
        ----------
        config
            Resolved CLI configuration containing API URL, timeout, and auth.
        http_client
            Optional pre-configured httpx.Client. If provided, it must already
            include appropriate ``User-Agent`` and ``Authorization`` headers.
            If not provided, a new client will be created with these headers.

        """
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.Client(
            base_url=config.api_base_url,
            timeout=config.request_timeout_s,
            headers=_headers_for(config),
        )

    @property
    def http_client(self) -> httpx.Client:
        """Expose the underlying `httpx.Client` for higher-level commands."""
        return self._http_client

    def request_json(
        self,
        method: http.HTTPMethod,
        path_segments: typ.Sequence[str],
        *,
        params: typ.Mapping[str, str] | None = None,
        body: typ.Mapping[str, object] | bytes | None = None,
    ) -> dict[str, object]:
        """Call one control-plane endpoint and return its JSON object.

        Each path segment is quoted separately so a value such as an owner
        containing ``/`` cannot change the route. A mapping body is serialized
        once, and the same bytes are used for the local size check and the
        request (O5); pre-encoded bytes are accepted so the command can enforce
        the limit without encoding twice.

        Parameters
        ----------
        method:
            HTTP method to use.
        path_segments:
            Unquoted path segments below the configured base URL.
        params:
            Optional query parameters.
        body:
            Optional JSON mapping or already-encoded body bytes.

        Returns
        -------
        dict[str, object]
            The decoded response document.

        Raises
        ------
        ControlPlaneHTTPError
            If the service answers with a non-2xx status.
        ControlPlaneTransportError
            If no response could be obtained.
        ControlPlaneTimeoutError
            If the request exceeded the configured timeout.
        ControlPlaneError
            If a successful response is not a JSON object.

        """
        path = "/" + "/".join(quote(segment, safe="") for segment in path_segments)
        content: bytes | None = None
        headers: dict[str, str] = {}
        if body is not None:
            content = body if isinstance(body, bytes) else encode_json_body(body)
            headers["Content-Type"] = "application/json"

        try:
            response = self._http_client.request(
                method,
                path,
                params=params,
                content=content,
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            message = "the control plane did not answer in time"
            raise ControlPlaneTimeoutError("timeout", message) from exc
        except httpx.RequestError as exc:
            # ``RequestError`` also covers redirect loops and decoding
            # failures, which are request failures as far as the operator is
            # concerned; letting them escape would print a traceback.
            message = "could not reach the control plane"
            raise ControlPlaneTransportError("transport", message) from exc

        if response.status_code >= _HTTP_ERROR_THRESHOLD:
            raise _http_error(response)
        return _success_document(response)

    def close(self) -> None:
        """Close the owned HTTP client."""
        if self._owns_client:
            self._http_client.close()

    def __enter__(self) -> ControlPlaneClient:
        """Enter a context manager scope."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Close the client when leaving a context manager scope."""
        self.close()


def _headers_for(config: ResolvedCliConfig) -> dict[str, str]:
    headers = {"User-Agent": "ghillie/0.1"}
    if config.auth_token:
        headers["Authorization"] = f"Bearer {config.auth_token}"
    return headers
