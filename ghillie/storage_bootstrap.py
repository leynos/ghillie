"""Opt-in schema bootstrap for self-hosted deployments (D13).

Managed deployments run migrations out of band, so the application must not
touch the schema by default. Setting ``GHILLIE_DB_BOOTSTRAP=create-all``
instead asks every replica to create any missing tables at start-up, which is
what a single-container or compose deployment needs.

``create_all`` checks for an existing table before issuing ``CREATE TABLE``.
Those two steps are not atomic, so replicas that start together can both see a
missing table and race on the DDL. PostgreSQL may fail the loser with a
duplicate-table error; that replica fails its start-up and the orchestrator
restarts it, at which point the table exists. Prefer a single bootstrap replica
or managed migrations when the platform cannot tolerate that restart.
"""

from __future__ import annotations

import typing as typ

from ghillie.bronze.storage import init_bronze_storage
from ghillie.catalogue.storage import init_catalogue_storage
from ghillie.gold.storage import init_gold_storage
from ghillie.logging import get_logger, log_info
from ghillie.silver.storage import init_silver_storage

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

__all__ = ["StorageBootstrapMiddleware", "init_all_storage"]

logger = get_logger(__name__)


async def init_all_storage(engine: AsyncEngine) -> None:
    """Create every layer's tables that are missing from *engine*.

    The layers are initialised in dependency order: bronze and silver own the
    ingestion tables, gold depends on repositories and reports, and the
    catalogue layer references repositories.

    Parameters
    ----------
    engine
        Async engine whose database receives the missing tables.

    """
    log_info(logger, "Creating missing storage tables (GHILLIE_DB_BOOTSTRAP)")
    await init_bronze_storage(engine)
    await init_silver_storage(engine)
    await init_gold_storage(engine)
    await init_catalogue_storage(engine)
    log_info(logger, "Storage bootstrap complete")


class StorageBootstrapMiddleware:
    """Falcon ASGI lifespan middleware running :func:`init_all_storage`.

    Parameters
    ----------
    engine
        Engine to bootstrap at ASGI start-up.

    """

    def __init__(self, engine: AsyncEngine) -> None:
        """Store the engine that start-up bootstraps."""
        self._engine = engine

    async def process_startup(self, _scope: typ.Any, _event: typ.Any) -> None:  # noqa: ANN401 - ASGI scope/event are untyped dicts.
        """Create missing tables before the server accepts requests."""
        await init_all_storage(self._engine)
