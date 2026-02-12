"""Gold layer API resources for on-demand report generation.

This module provides the ``ReportResource`` which handles
``POST /reports/repositories/{owner}/{name}`` requests, triggering
report generation through the same pipeline as scheduled reports.

Usage
-----
Register the resource on the Falcon app::

    from ghillie.api.gold.resources import ReportResource

    app.add_route(
        "/reports/repositories/{owner}/{name}",
        ReportResource(reporting_service=reporting_service),
    )

"""

from __future__ import annotations

import typing as typ

import falcon
from sqlalchemy import select

from ghillie.api.errors import RepositoryNotFoundError
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    from falcon.asgi import Request, Response
    from sqlalchemy.ext.asyncio import AsyncSession

    from ghillie.gold.storage import Report
    from ghillie.reporting.service import ReportingService

__all__ = ["ReportResource"]


def _serialize_report(report: Report, slug: str) -> dict[str, typ.Any]:
    """Serialize a Gold ``Report`` to a JSON-compatible dict."""
    return {
        "report_id": report.id,
        "repository": slug,
        "window_start": report.window_start.isoformat(),
        "window_end": report.window_end.isoformat(),
        "generated_at": report.generated_at.isoformat(),
        "status": report.machine_summary.get("status", "unknown"),
        "model": report.model or "unknown",
    }


class ReportResource:
    """Resource for on-demand report generation.

    ``POST /reports/repositories/{owner}/{name}`` triggers report
    generation for the specified repository using the same pipeline
    as scheduled reports.  The resource expects the middleware to
    attach a request-scoped ``AsyncSession`` to ``req.context.session``.

    Parameters
    ----------
    reporting_service
        Service for generating reports on demand.

    """

    def __init__(
        self,
        *,
        reporting_service: ReportingService,
    ) -> None:
        """Configure the resource with its dependencies.

        Parameters
        ----------
        reporting_service
            Service for generating reports on demand.

        """
        self._reporting_service = reporting_service

    async def on_post(
        self,
        req: Request,
        resp: Response,
        *,
        owner: str,
        name: str,
    ) -> None:
        """Handle POST request to generate a report on demand.

        Parameters
        ----------
        req
            Falcon request object.
        resp
            Falcon response object.
        owner
            GitHub repository owner from URL path.
        name
            GitHub repository name from URL path.

        """
        session: AsyncSession = req.context.session
        repo_id = await self._resolve_repository(session, owner, name)

        report = await self._reporting_service.run_for_repository(repo_id)

        if report is None:
            resp.status = falcon.HTTP_204
            return

        slug = f"{owner}/{name}"
        resp.media = _serialize_report(report, slug)
        resp.status = falcon.HTTP_200

    async def _resolve_repository(
        self,
        session: AsyncSession,
        owner: str,
        name: str,
    ) -> str:
        """Look up a repository by owner/name and return its ID."""
        stmt = select(Repository.id).where(
            Repository.github_owner == owner,
            Repository.github_name == name,
        )
        repo_id: str | None = await session.scalar(stmt)

        if repo_id is None:
            raise RepositoryNotFoundError(owner, name)

        return repo_id
