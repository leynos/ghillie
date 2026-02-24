"""Shared dataclass and protocol definitions for test fixtures.

Provides frozen dataclasses and ``typing.Protocol`` types that
parameterise fixture helpers across the test suite.  Import the types
you need and instantiate them with test-specific values:

Examples
--------
Create a repository with default settings::

    from tests.fixtures.specs import RepositoryParams

    params = RepositoryParams(
        owner="leynos",
        name="wildside",
        catalogue_repository_id="cat-1",
        estate_id="estate-1",
    )

Override report summary defaults::

    from tests.fixtures.specs import ReportSummaryParams

    summary = ReportSummaryParams(status="at_risk", summary="Behind.")

"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import datetime as dt

    from ghillie.silver.storage import Repository


# ---------------------------------------------------------------------------
# Registry / repository specs
# ---------------------------------------------------------------------------


@dc.dataclass(frozen=True, slots=True)
class RepositoryCreateSpec:
    """Fields used when creating Silver Repository rows in tests."""

    ingestion_enabled: bool = True
    default_branch: str = "main"
    estate_id: str | None = None
    catalogue_repository_id: str | None = None
    documentation_paths: tuple[str, ...] | None = None


class CreateRepoFn(typ.Protocol):
    """Callable fixture for creating Silver repositories."""

    def __call__(
        self,
        owner: str,
        name: str,
        *,
        spec: RepositoryCreateSpec | None = None,
    ) -> cabc.Awaitable[None]:
        """Create a Silver repository row."""
        ...


class FetchRepoFn(typ.Protocol):
    """Callable fixture for fetching repositories."""

    def __call__(self, owner: str, name: str) -> cabc.Awaitable[Repository | None]:
        """Fetch a repository by owner/name."""
        ...


# ---------------------------------------------------------------------------
# Reporting specs
# ---------------------------------------------------------------------------


@dc.dataclass(frozen=True, slots=True)
class RepositoryEventSpec:
    """Encapsulates test repository and event data for helper functions.

    Groups the four test-data parameters that are always passed together
    when setting up a repository with a commit event, reducing the
    parameter count of ``setup_test_repository_with_event``.

    .. note:: The name avoids the ``Test`` prefix so pytest does not
       attempt to collect this dataclass as a test class.
    """

    owner: str = "acme"
    name: str = "widget"
    commit_hash: str = "test001"
    commit_time: dt.datetime | None = None


# ---------------------------------------------------------------------------
# Project evidence specs
# ---------------------------------------------------------------------------


@dc.dataclass(frozen=True, slots=True)
class RepositoryParams:
    """Parameters for creating a Silver Repository linked to catalogue."""

    owner: str
    name: str
    catalogue_repository_id: str
    estate_id: str


@dc.dataclass(frozen=True, slots=True)
class ReportSummaryParams:
    """Parameters for creating a Gold Report machine summary."""

    status: str = "on_track"
    summary: str = "Progress is on track."
    highlights: tuple[str, ...] = ("Feature shipped",)
    risks: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()


@dc.dataclass(frozen=True, slots=True)
class ReportSpec:
    """Specification for a single Gold Report in multi-report helpers."""

    window_start: dt.datetime
    window_end: dt.datetime
    generated_at: dt.datetime
    status: str
    summary: str


@dc.dataclass(frozen=True, slots=True)
class ProjectReportParams:
    """Parameters for creating a project-scope Gold Report."""

    project_key: str
    project_name: str
    estate_id: str
    window_start: dt.datetime
    window_end: dt.datetime
    generated_at: dt.datetime | None = None
    status: str = "on_track"
    highlights: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
