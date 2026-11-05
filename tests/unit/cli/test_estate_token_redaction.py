"""The API token and URL credentials never reach operator-visible output.

D14 keeps the token out of logs and errors; O4 keeps failure text stable. A
distinctive token and a base URL carrying ``user:pass@`` make any leak
unmistakable, including when the service returns ``500``, is unreachable, or
answers with a non-JSON body.
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
_BASE_URL = "http://operator:hunter2@127.0.0.1:9999"


def _assert_no_secret(*texts: str) -> None:
    combined = "\n".join(texts)
    assert _TOKEN not in combined, "the bearer token leaked into output"
    assert "hunter2" not in combined, "the URL password leaked into output"
    assert "operator:hunter2" not in combined


def test_token_is_sent_but_never_printed_on_success(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The header proves the token was used; the output proves it stayed out."""
    client = harness(api_base_url=_BASE_URL, auth_token=_TOKEN)
    client.queue_json(
        {
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
    )

    result = typ.cast("str", client.invoke(sync, estate_key="demo"))

    # ``httpx`` replaces the bearer header with basic auth when the URL carries
    # credentials, so only the presence of authentication is asserted here.
    assert client.requests[0].headers["authorization"]
    captured = capsys.readouterr()
    _assert_no_secret(result, captured.out, captured.err)


@pytest.mark.parametrize(
    "respond",
    [
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
    ],
)
def test_failures_never_print_the_token_or_url_credentials(
    harness: typ.Callable[..., CliHarness],
    capsys: pytest.CaptureFixture[str],
    respond: typ.Callable[[CliHarness], None],
) -> None:
    """Every failure path keeps secrets out of standard error and logs."""
    client = harness(api_base_url=_BASE_URL, auth_token=_TOKEN, output="json")
    respond(client)

    with capture_femto_logs("ghillie.cli") as logs:
        result = client.invoke(sync, estate_key="demo")
        logs.wait_for_timeout()

    assert result == 3
    captured = capsys.readouterr()
    _assert_no_secret(captured.out, captured.err)
    _assert_no_secret(*(record.message for record in logs.records))
