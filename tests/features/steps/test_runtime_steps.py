"""Behavioural coverage for the Ghillie runtime service."""

from __future__ import annotations

import typing as typ

import falcon.testing
import pytest
from pytest_bdd import given, parsers, scenario, then, when

if typ.TYPE_CHECKING:
    from falcon.testing.client import Result


class RuntimeContext(typ.TypedDict, total=False):
    """Shared mutable scenario state."""

    client: falcon.testing.TestClient
    response: Result


@scenario(
    "../runtime.feature",
    "Health endpoint returns ok status",
)
def test_health_endpoint_returns_ok() -> None:
    """Wrap the pytest-bdd scenario for health endpoint."""


@scenario(
    "../runtime.feature",
    "Ready endpoint returns ready status",
)
def test_ready_endpoint_returns_ready() -> None:
    """Wrap the pytest-bdd scenario for ready endpoint."""


@pytest.fixture
def runtime_context() -> RuntimeContext:
    """Provision a test client for the runtime app."""
    from ghillie.runtime import create_app

    client = falcon.testing.TestClient(create_app())
    return {"client": client}


@given("a running Ghillie runtime app")
def given_running_app(runtime_context: RuntimeContext) -> None:
    """Ensure the runtime app is available via the test client."""
    # The fixture provides the client; this step is a placeholder for setup.
    assert "client" in runtime_context, "client should be set by fixture"


@when(parsers.parse("I request GET {path}"))
def when_request_get(runtime_context: RuntimeContext, path: str) -> None:
    """Issue a GET request to the given path."""
    client = runtime_context["client"]
    runtime_context["response"] = client.simulate_get(path)


@then(parsers.parse("the response status is {status:d}"))
def then_response_status(runtime_context: RuntimeContext, status: int) -> None:
    """Assert the HTTP response status code."""
    response = runtime_context["response"]
    assert response.status_code == status, (
        f"expected status {status}, got {response.status_code}"
    )


@then(parsers.parse('the response body is {{"status": "{expected_status}"}}'))
def then_response_body_status(
    runtime_context: RuntimeContext, expected_status: str
) -> None:
    """Assert the response JSON body contains the expected status."""
    response = runtime_context["response"]
    assert response.json == {"status": expected_status}, (
        f"expected {{'status': '{expected_status}'}}, got {response.json}"
    )
