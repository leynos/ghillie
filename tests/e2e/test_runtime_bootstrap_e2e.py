"""End-to-end proof that Granian's lifespan event reaches the bootstrap hook.

The packaged runtime is started against a fresh database with
``GHILLIE_DB_BOOTSTRAP=create-all``. Nothing else in that process creates the
storage tables, so their presence, together with the two log lines emitted by
``init_all_storage``, shows Granian delivered the ASGI startup event to
``StorageBootstrapMiddleware.process_startup``.
"""

from __future__ import annotations

import sqlite3
import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from tests.e2e.conftest import GhillieServer

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(120)]

_RUNTIME_STARTED = "Starting Ghillie runtime on"
_BOOTSTRAP_STARTED = "Creating missing storage tables (GHILLIE_DB_BOOTSTRAP)"
_BOOTSTRAP_COMPLETE = "Storage bootstrap complete"

# One table from each layer that ``init_all_storage`` creates, so a partial
# bootstrap cannot satisfy the assertion.
_EXPECTED_TABLES = frozenset(
    {"repositories", "raw_events", "commits", "reports", "estates"}
)


def _table_names(database: str) -> set[str]:
    """Return the table names stored in *database*."""
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row[0] for row in rows}


def test_granian_delivers_startup_to_the_bootstrap_hook(
    ghillie_server: GhillieServer,
) -> None:
    """A fresh database is bootstrapped by the ASGI startup callback."""
    log_text = ghillie_server.log_text()

    # The log is written in order, so these positions show the callback ran
    # inside the Granian-served application after it announced itself.
    assert _RUNTIME_STARTED in log_text, log_text
    assert _BOOTSTRAP_STARTED in log_text, log_text
    assert _BOOTSTRAP_COMPLETE in log_text, log_text
    assert log_text.index(_RUNTIME_STARTED) < log_text.index(_BOOTSTRAP_STARTED)
    assert log_text.index(_BOOTSTRAP_STARTED) < log_text.index(_BOOTSTRAP_COMPLETE)

    tables = _table_names(str(ghillie_server.database))
    assert tables >= _EXPECTED_TABLES, sorted(tables)
