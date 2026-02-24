"""High-level project-evidence test helpers.

Convenience wrappers that compose lower-level helpers from
:mod:`tests.unit.project_evidence_helpers` into ready-made bundles
for use in unit tests.

Examples
--------
Build a Wildside bundle in a test::

    from tests.unit.helpers.project_evidence_helpers import (
        build_wildside_bundle,
    )

"""

from __future__ import annotations

import asyncio
import typing as typ

from tests.unit.project_evidence_helpers import get_estate_id

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.evidence.models import ProjectEvidenceBundle
    from ghillie.evidence.project_service import ProjectEvidenceBundleService


def build_wildside_bundle(
    service: ProjectEvidenceBundleService,
    session_factory: async_sessionmaker[AsyncSession],
) -> ProjectEvidenceBundle:
    """Build and return a bundle for the Wildside project.

    Parameters
    ----------
    service
        The ``ProjectEvidenceBundleService`` under test.
    session_factory
        Async session factory for database access.

    Returns
    -------
    ProjectEvidenceBundle
        The assembled evidence bundle for the Wildside project.

    """
    eid = get_estate_id(session_factory)
    return asyncio.run(service.build_bundle("wildside", eid))
