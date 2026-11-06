"""The API token and URL credentials never reach operator-visible output.

D14 keeps the token out of logs and errors; O4 keeps failure text stable. A
distinctive token and a base URL carrying ``user:pass@`` make any leak
unmistakable, including when the service returns ``500``, is unreachable, or
answers with a non-JSON body.

The bearer-token and URL-credential cases are separate tests: ``httpx``
replaces a bearer header with basic auth when the URL carries credentials, so
asserting the bearer value against a credential-bearing URL would prove
nothing.
"""

from __future__ import annotations

import typing as typ

import httpx
import pytest

from ghillie.cli.commands.estate import sync
from tests.helpers.femtologging_capture import capture_femto_logs

if typ.TYPE_CHECKING:
    from tests.unit.cli.harness import CliHarness

_TOKEN = "s3cr3t-token-value"  # noqa: S105 - a fake token, not a credential
_BASE_URL = "http://127.0.0.1:9999"
_CREDENTIALS_URL = "http://operator:hunter2@127.0.0.1:9999"

_SYNC_PAYLOAD: dict[str, object] = {
    "estate_key": "demo",
    "state": "succeeded",
    "dry_run": False,
    "repositories_created": 1,
    "repositories_updated": 0,
    "repositories_deactivated": 0,
    "repositories_conflicted": [],
    "repositories_left_disabled": [],
    "repositories_left_disabled_count": 0,
}


def _assert_no_url_password(*texts: str) -> None:
    combined = "\n".join(texts)
    assert "hunter2" not in combined, "the URL password leaked into output"
    assert "operator:hunter2" not in combined


def test_the_bearer_token_is_sent_but_never_printed(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The header proves the token was used; the output proves it stayed out."""
    client = harness(api_base_url=_BASE_URL, auth_token=_TOKEN)
    client.queue_json(_SYNC_PAYLOAD)

    result = typ.cast("str", client.invoke(sync, estate_key="demo"))

    assert client.requests[0].headers["authorization"] == f"Bearer {_TOKEN}"
    captured = capsys.readouterr()
    combined = "\n".join((result, captured.out, captured.err))
    assert _TOKEN not in combined, "the bearer token leaked into output"


def test_url_credentials_are_used_but_never_printed(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A credential-bearing base URL authenticates without echoing the secret."""
    client = harness(api_base_url=_CREDENTIALS_URL)
    client.queue_json(_SYNC_PAYLOAD)

    result = typ.cast("str", client.invoke(sync, estate_key="demo"))

    assert client.requests[0].headers["authorization"].startswith("Basic ")
    captured = capsys.readouterr()
    _assert_no_url_password(result, captured.out, captured.err)


_RESPONDERS = [
    pytest.param(
        lambda client: client.queue_json(
            {"title": "Internal Server Error", "description": "boom"},
            status=500,
        ),
        id="http-500",
    ),
    pytest.param(
        lambda client: client.queue_raw("<html>bad gateway</html>", status=502),
        id="non-json",
    ),
    pytest.param(
        lambda client: client.queue_error(httpx.ConnectError("refused")),
        id="transport",
    ),
    pytest.param(
        lambda client: client.queue_error(httpx.ReadTimeout("timed out")),
        id="timeout",
    ),
]


class _SecretCase(typ.NamedTuple):
    """One credential route and the value that must never be printed."""

    api_base_url: str
    auth_token: str | None
    secret: str


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(_SecretCase(_BASE_URL, _TOKEN, _TOKEN), id="bearer-token"),
        pytest.param(
            _SecretCase(_CREDENTIALS_URL, None, "hunter2"), id="url-credentials"
        ),
    ],
)
@pytest.mark.parametrize("respond", _RESPONDERS)
def test_failures_never_print_a_secret(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
    respond: typ.Callable[[CliHarness], None],
    case: _SecretCase,
) -> None:
    """Every failure path keeps its secret out of standard error and logs."""
    api_base_url, auth_token, secret = case
    client = harness(
        api_base_url=api_base_url,
        auth_token=auth_token,
        output="json",
    )
    respond(client)

    with capture_femto_logs("ghillie.cli") as logs:
        result = client.invoke(sync, estate_key="demo")
        logs.wait_for_timeout()

    assert result == 3
    captured = capsys.readouterr()
    combined = "\n".join(
        (captured.out, captured.err, *(record.message for record in logs.records))
    )
    assert secret not in combined, f"{secret!r} leaked into output or logs"
    _assert_no_url_password(combined)
