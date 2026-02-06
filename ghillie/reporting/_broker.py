"""Broker configuration helpers for Dramatiq actor setup.

This private module encapsulates the broker detection and configuration logic
used at actor invocation time to ensure a Dramatiq broker is available.
"""

from __future__ import annotations

import os
import sys
import threading

import dramatiq
from dramatiq.brokers.stub import StubBroker

_BROKER_LOCK = threading.Lock()
_broker_configured = False


def _is_running_tests() -> bool:
    """Check if the current process is running in a test environment.

    Detects pytest by checking for the pytest module in sys.modules or
    pytest-specific environment variables set by pytest and pytest-xdist.

    Returns
    -------
    bool
        True if running under pytest, False otherwise.

    """
    return "pytest" in sys.modules or any(
        key in os.environ
        for key in ["PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER", "PYTEST_ADDOPTS"]
    )


def _should_use_stub_broker() -> bool:
    """Determine whether to use a StubBroker instead of a real broker.

    Returns True if either the GHILLIE_ALLOW_STUB_BROKER environment variable
    is set to a truthy value, or if we're running in a test environment.

    Returns
    -------
    bool
        True if a StubBroker should be used, False otherwise.

    """
    allow_stub = os.environ.get("GHILLIE_ALLOW_STUB_BROKER", "")
    return allow_stub.lower() in {"1", "true", "yes"} or _is_running_tests()


def ensure_broker_configured() -> None:
    """Ensure a Dramatiq broker is configured before actor execution.

    Thread-safe: uses a lock and sentinel to guarantee idempotent
    configuration even when called concurrently from multiple Dramatiq
    worker threads.

    This function checks for an existing broker and sets up a StubBroker
    in test environments. It is called at the start of each actor function
    rather than at import time to avoid premature global state mutation.

    Raises
    ------
    RuntimeError
        If no broker is configured and we're not in a test/stub-allowed context.

    """
    global _broker_configured

    if _broker_configured:
        return

    with _BROKER_LOCK:
        # Double-check after acquiring the lock
        if _broker_configured:
            return

        try:  # pragma: no cover - exercised in tests and CLI usage
            current_broker = dramatiq.get_broker()
        except (ImportError, LookupError):
            # ImportError: broker dependencies (RabbitMQ/Redis) are not installed
            # LookupError: no broker has been configured yet
            current_broker = None

        if current_broker is None:
            if _should_use_stub_broker():
                dramatiq.set_broker(StubBroker())
            else:  # pragma: no cover - guard for prod misconfigurations
                message = (
                    "No Dramatiq broker configured. "
                    "Set GHILLIE_ALLOW_STUB_BROKER=1 for "
                    "local/test runs or configure a real broker."
                )
                raise RuntimeError(message)

        _broker_configured = True
