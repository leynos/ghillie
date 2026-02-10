"""Gold layer API resources for on-demand report generation.

This module provides the ``ReportResource`` which handles
``POST /reports/repositories/{owner}/{name}`` requests, triggering
report generation through the same pipeline as scheduled reports.

Usage
-----
Register the resource on the Falcon app::

    app.add_route(
        "/reports/repositories/{owner}/{name}",
        ReportResource(dependencies),
    )

"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

import falcon
from sqlalchemy import select

from ghillie.api.errors import RepositoryNotFoundError
from ghillie.silver.storage import Repository

if typ.TYPE_CHECKING:
    from falcon.asgi import Request, Response
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.gold.storage import Report
    from ghillie.reporting.service import ReportingService

__all__ = ["ReportResource", "ReportResourceDependencies"]


@dc.dataclass(frozen=True, slots=True)
class ReportResourceDependencies:
    """Dependencies for ``ReportResource``.

    Groups the mandatory collaborators into a single parameter object,
    keeping the constructor argument count within lint thresholds.

    Attributes
    ----------
    session_factory
        Async session factory for repository lookups.
    reporting_service
        Service for generating reports on demand.

    """

    session_factory: async_sessionmaker[AsyncSession]
    reporting_service: ReportingService


def _serialize_report(report: Report, slug: str) -> dict[str, typ.Any]:
    """Serialize a Gold ``Report`` to a JSON-compatible dict.

    Parameters
    ----------
    report
        The persisted Gold layer report.
    slug
        Repository slug (``owner/name``).

    Returns
    -------
    dict[str, Any]
        JSON-serializable report metadata.

    """
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
    as scheduled reports.

    """

    def __init__(self, dependencies: ReportResourceDependencies) -> None:
        """Configure the resource with its dependencies.

        Parameters
        ----------
        dependencies
            Grouped collaborators for the resource.

        """
        self._session_factory = dependencies.session_factory
        self._reporting_service = dependencies.reporting_service

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
        repo_id = await self._resolve_repository(owner, name)

        report = await self._reporting_service.run_for_repository(repo_id)

        if report is None:
            resp.status = falcon.HTTP_204
            return

        slug = f"{owner}/{name}"
        resp.media = _serialize_report(report, slug)
        resp.status = falcon.HTTP_200

    async def _resolve_repository(self, owner: str, name: str) -> str:
        """Look up a repository by owner/name and return its ID.

        Parameters
        ----------
        owner
            GitHub repository owner.
        name
            GitHub repository name.

        Returns
        -------
        str
            The Silver layer repository ID.

        Raises
        ------
        RepositoryNotFoundError
            If no repository matches the given owner/name.

        """
        async with self._session_factory() as session:
            stmt = select(Repository.id).where(
                Repository.github_owner == owner,
                Repository.github_name == name,
            )
            repo_id: str | None = await session.scalar(stmt)

        if repo_id is None:
            raise RepositoryNotFoundError(owner, name)

        return repo_id
