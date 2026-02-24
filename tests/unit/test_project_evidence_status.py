"""Unit tests for project evidence status mapping.

Verifies that ``ProjectEvidenceBundleService.build_bundle`` correctly maps
edge-case ``machine_summary.status`` values (``None``, mixed case, invalid
strings, non-string types) to the appropriate ``ReportStatus`` enum member.

Examples
--------
Run these tests::

    pytest tests/unit/test_project_evidence_status.py -q

"""

from __future__ import annotations

import asyncio
import typing as typ

import pytest

from ghillie.evidence.models import ReportStatus
from tests.fixtures.specs import RepositoryParams
from tests.unit.project_evidence_helpers import (
    create_silver_repo_and_report_raw,
    get_catalogue_repo_ids,
    get_estate_id,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ghillie.evidence.project_service import ProjectEvidenceBundleService


@pytest.mark.usefixtures("_import_wildside")
class TestStatusMappingViaBuildBundle:
    """Verify status parsing through the public ``build_bundle`` API.

    Notes
    -----
    Each parametrized case creates a Silver Repository and Gold Report
    whose ``machine_summary.status`` is set to the given edge-case value,
    then asserts that the resulting component summary maps it to the
    correct ``ReportStatus`` enum member.

    """

    @pytest.mark.parametrize(
        ("machine_summary_status", "expected_status"),
        [
            pytest.param(None, ReportStatus.UNKNOWN, id="none"),
            pytest.param("On_TrAcK", ReportStatus.ON_TRACK, id="mixed-case"),
            pytest.param("nonsense", ReportStatus.UNKNOWN, id="invalid-string"),
            pytest.param(123, ReportStatus.UNKNOWN, id="non-string-int"),
        ],
    )
    def test_status_mapping_from_reports(
        self,
        project_evidence_service: ProjectEvidenceBundleService,
        session_factory: async_sessionmaker[AsyncSession],
        machine_summary_status: object,
        expected_status: ReportStatus,
    ) -> None:
        """Component summary status reflects edge-case ``machine_summary`` values.

        Parameters
        ----------
        project_evidence_service
            The service under test.
        session_factory
            Async session factory for database access.
        machine_summary_status
            Raw status value stored in the Gold Report's ``machine_summary``.
        expected_status
            The ``ReportStatus`` enum member expected after mapping.

        """
        eid = get_estate_id(session_factory)
        repo_ids = get_catalogue_repo_ids(session_factory)

        create_silver_repo_and_report_raw(
            session_factory,
            RepositoryParams(
                owner="leynos",
                name="wildside",
                catalogue_repository_id=repo_ids["leynos/wildside"],
                estate_id=eid,
            ),
            machine_summary={
                "status": machine_summary_status,
                "summary": "Test.",
                "highlights": [],
                "risks": [],
                "next_steps": [],
            },
        )

        bundle = asyncio.run(project_evidence_service.build_bundle("wildside", eid))
        core = next(c for c in bundle.components if c.key == "wildside-core")

        assert core.repository_summary is not None, (
            "wildside-core should have a summary"
        )
        assert core.repository_summary.status is expected_status, (
            f"expected {expected_status!r} for input {machine_summary_status!r}, "
            f"got {core.repository_summary.status!r}"
        )
