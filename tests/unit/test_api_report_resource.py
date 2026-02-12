"""Unit tests for ghillie.api.gold.resources.ReportResource.

Usage
-----
Run with pytest::

    pytest tests/unit/test_api_report_resource.py

"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
from unittest import mock

import falcon.asgi
import falcon.testing
import pytest

from ghillie.api.app import AppDependencies, create_app


@dc.dataclass(frozen=True, slots=True)
class _ReportFields:
    """Fields for building a mock Report."""

    report_id: str = "rpt-001"
    window_start: dt.datetime | None = None
    window_end: dt.datetime | None = None
    generated_at: dt.datetime | None = None
    model: str | None = "mock-v1"
    machine_summary: dict[str, str | int | float | bool] | None = None


def _make_report(fields: _ReportFields | None = None) -> mock.MagicMock:
    """Build a mock Report object with realistic field values."""
    f = fields or _ReportFields()
    report = mock.MagicMock()
    report.id = f.report_id
    report.window_start = f.window_start or dt.datetime(2024, 7, 7, tzinfo=dt.UTC)
    report.window_end = f.window_end or dt.datetime(2024, 7, 14, tzinfo=dt.UTC)
    report.generated_at = f.generated_at or dt.datetime(
        2024, 7, 14, 12, 0, tzinfo=dt.UTC
    )
    report.model = f.model
    report.machine_summary = (
        f.machine_summary if f.machine_summary is not None else {"status": "on_track"}
    )
    return report


_DEFAULT_REPORT_SENTINEL = object()


@pytest.fixture
def report_client() -> falcon.testing.TestClient:
    """Build a test client with a generated report."""
    return _build_client()


def _build_client(
    *,
    resolve_repo_id: str | None = "repo-abc",
    run_result: mock.MagicMock | None | object = _DEFAULT_REPORT_SENTINEL,
) -> falcon.testing.TestClient:
    """Build a test client with a mocked ReportResource."""
    if run_result is _DEFAULT_REPORT_SENTINEL:
        run_result = mock.MagicMock()

    mock_session_factory = mock.MagicMock()

    # Build a mock async context manager for the session
    mock_session = mock.MagicMock()
    mock_scalar = mock.AsyncMock(return_value=resolve_repo_id)
    mock_session.scalar = mock_scalar

    mock_cm = mock.AsyncMock()
    mock_cm.__aenter__ = mock.AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = mock.AsyncMock(return_value=False)
    mock_session_factory.return_value = mock_cm

    mock_reporting_service = mock.MagicMock()
    mock_reporting_service.run_for_repository = mock.AsyncMock(return_value=run_result)

    deps = AppDependencies(
        session_factory=mock_session_factory,
        reporting_service=mock_reporting_service,
    )
    app = create_app(deps)
    return falcon.testing.TestClient(app)


class TestReportResource200:
    """POST returns 200 with report metadata when a report is generated."""

    def test_returns_200(self) -> None:
        """Successful generation returns HTTP 200."""
        report = _make_report()
        client = _build_client(run_result=report)
        result = client.simulate_post("/reports/repositories/acme/widgets")
        assert result.status == falcon.HTTP_200, "expected HTTP 200"

    def test_response_has_report_id(self) -> None:
        """Response body includes report_id."""
        report = _make_report(_ReportFields(report_id="rpt-42"))
        client = _build_client(run_result=report)
        result = client.simulate_post("/reports/repositories/acme/widgets")
        assert result.json["report_id"] == "rpt-42", "wrong report_id"

    def test_response_has_repository_slug(self) -> None:
        """Response body includes the repository slug."""
        report = _make_report()
        client = _build_client(run_result=report)
        result = client.simulate_post("/reports/repositories/acme/widgets")
        assert result.json["repository"] == "acme/widgets", "wrong slug"

    def test_response_has_window_dates(self) -> None:
        """Response body includes ISO-formatted window dates."""
        report = _make_report()
        client = _build_client(run_result=report)
        result = client.simulate_post("/reports/repositories/acme/widgets")
        assert "window_start" in result.json, "missing window_start"
        assert "window_end" in result.json, "missing window_end"

    def test_response_has_status(self) -> None:
        """Response body includes the status from machine_summary."""
        report = _make_report(_ReportFields(machine_summary={"status": "at_risk"}))
        client = _build_client(run_result=report)
        result = client.simulate_post("/reports/repositories/acme/widgets")
        assert result.json["status"] == "at_risk", "wrong status"

    def test_response_status_falls_back_to_unknown(self) -> None:
        """Response status defaults to 'unknown' when machine_summary lacks status."""
        report = _make_report(_ReportFields(machine_summary={}))
        client = _build_client(run_result=report)
        result = client.simulate_post("/reports/repositories/acme/widgets")
        assert result.json["status"] == "unknown", "expected 'unknown' fallback"

    def test_response_model_falls_back_to_unknown(self) -> None:
        """Response model defaults to 'unknown' when model metadata is missing."""
        report = _make_report(_ReportFields(model=None))
        client = _build_client(run_result=report)
        result = client.simulate_post("/reports/repositories/acme/widgets")
        assert result.json["model"] == "unknown", "expected 'unknown' fallback"

    def test_response_content_type_is_json(self) -> None:
        """Response content type is application/json."""
        report = _make_report()
        client = _build_client(run_result=report)
        result = client.simulate_post("/reports/repositories/acme/widgets")
        content_type = result.headers.get("content-type", "")
        assert content_type.startswith("application/json"), "wrong content type"


class TestReportResource204:
    """POST returns 204 when no events exist in the reporting window."""

    def test_returns_204_no_events(self) -> None:
        """Returns HTTP 204 when run_for_repository returns None."""
        client = _build_client(run_result=None)
        result = client.simulate_post("/reports/repositories/acme/widgets")
        assert result.status == falcon.HTTP_204, "expected HTTP 204"


class TestReportResource404:
    """POST returns 404 when the repository slug is unknown."""

    def test_returns_404_unknown_repo(self) -> None:
        """Returns HTTP 404 when repository is not found."""
        client = _build_client(resolve_repo_id=None)
        result = client.simulate_post("/reports/repositories/unknown/repo")
        assert result.status == falcon.HTTP_404, "expected HTTP 404"

    def test_404_body_has_description(self) -> None:
        """404 response body includes the repository slug."""
        client = _build_client(resolve_repo_id=None)
        result = client.simulate_post("/reports/repositories/unknown/repo")
        assert "unknown/repo" in result.json["description"], "missing slug"
