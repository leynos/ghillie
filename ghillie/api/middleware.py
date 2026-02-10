"""SQLAlchemy session middleware for Falcon ASGI applications.

Provides request-scoped ``AsyncSession`` instances via ``req.context.session``,
following the pattern documented in ``docs/async-sqlalchemy-with-pg-and-falcon.md``.

The middleware creates a fresh session on each request and handles
commit/rollback/close in ``process_response``, ensuring connections are
returned to the pool regardless of outcome.

Usage
-----
Register the middleware when creating the Falcon app::

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from ghillie.api.middleware import SQLAlchemySessionManager

    session_mw = SQLAlchemySessionManager(session_factory)
    app = falcon.asgi.App(middleware=[session_mw])

"""

from __future__ import annotations

import typing as typ

from ghillie.logging import get_logger, log_error

if typ.TYPE_CHECKING:
    from falcon.asgi import Request, Response
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

__all__ = ["SQLAlchemySessionManager"]

logger = get_logger(__name__)


class SQLAlchemySessionManager:
    """Falcon middleware providing request-scoped async SQLAlchemy sessions.

    Each incoming request receives a fresh ``AsyncSession`` attached to
    ``req.context.session``.  On response, the session is committed on
    success (2xx/3xx) or rolled back on error (4xx/5xx), and always
    closed to return the connection to the pool.

    Parameters
    ----------
    session_factory
        Async session factory bound to the application's database engine.

    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Initialize the middleware with a session factory.

        Parameters
        ----------
        session_factory
            Async session factory bound to the application's database engine.

        """
        self._session_factory = session_factory

    async def process_request(self, req: Request, _resp: Response) -> None:
        """Attach a fresh ``AsyncSession`` to ``req.context.session``."""
        req.context.session = self._session_factory()

    async def process_response(
        self,
        req: Request,
        resp: Response,
        _resource: object,
        req_succeeded: bool,  # noqa: FBT001 - Falcon middleware signature
    ) -> None:
        """Commit on success, rollback on error, close always."""
        session: AsyncSession | None = getattr(req.context, "session", None)
        if session is None:
            return

        try:
            if session.is_active:
                status = str(resp.status)
                if req_succeeded and not status.startswith(("4", "5")):
                    await session.commit()
                else:
                    await session.rollback()
        except Exception:
            log_error(
                logger,
                "Session cleanup failed during process_response",
            )
            if session.is_active:
                await session.rollback()
            raise
        finally:
            await session.close()
