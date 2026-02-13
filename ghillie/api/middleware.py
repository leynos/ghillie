"""SQLAlchemy session middleware for Falcon ASGI applications.

Provides request-scoped ``AsyncSession`` instances via ``req.context.session``,
following the pattern documented in ``docs/async-sqlalchemy-with-pg-and-falcon.md``.

The middleware creates a fresh session on each request (without ``async with``,
since it manages commit/rollback/close explicitly in ``process_response``) and
ensures connections are returned to the pool regardless of outcome.  Resources
should reuse the request-scoped session via ``req.context.session`` rather than
opening new sessions from the factory.

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

from sqlalchemy.exc import SQLAlchemyError

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
        """Attach a fresh ``AsyncSession`` to ``req.context.session``.

        The session is created via a bare ``session_factory()`` call rather
        than ``async with session_factory()`` because the middleware needs to
        keep the session open across ``process_request`` and
        ``process_response``.  Commit, rollback, and close are handled
        explicitly in :meth:`_finalize_session`.

        Parameters
        ----------
        req
            Falcon request whose context receives the session.
        _resp
            Falcon response (unused during request phase).

        """
        req.context.session = self._session_factory()

    def _should_commit(self, resp: Response, *, req_succeeded: bool) -> bool:
        """Return whether the response indicates a committable outcome."""
        status = str(resp.status)
        return req_succeeded and not status.startswith(("4", "5"))

    async def _finalize_session(
        self,
        session: AsyncSession,
        resp: Response,
        *,
        req_succeeded: bool,
    ) -> None:
        """Commit or rollback *session* and close it."""
        try:
            if session.is_active:
                if self._should_commit(resp, req_succeeded=req_succeeded):
                    await session.commit()
                else:
                    await session.rollback()
        except SQLAlchemyError:
            log_error(
                logger,
                "Session cleanup failed during process_response",
                exc_info=True,
            )
            if session.is_active:
                await session.rollback()
            raise
        finally:
            await session.close()

    async def process_response(
        self,
        req: Request,
        resp: Response,
        _resource: object,
        req_succeeded: bool,  # noqa: FBT001 -- FIXME: Falcon middleware signature requires positional bool
    ) -> None:
        """Commit on success, rollback on error, close always.

        Parameters
        ----------
        req
            Falcon request carrying the session in its context.
        resp
            Falcon response used to determine success/failure.
        _resource
            The matched Falcon resource (unused).
        req_succeeded
            ``True`` when no unhandled exception occurred during the
            request phase.

        """
        session: AsyncSession | None = getattr(req.context, "session", None)
        if session is None:
            return

        await self._finalize_session(session, resp, req_succeeded=req_succeeded)
