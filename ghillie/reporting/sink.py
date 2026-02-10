"""ReportSink protocol for writing rendered Markdown reports.

This module defines the port (in hexagonal architecture terms) for
report output. Adapters implement this protocol to write reports to
various backends: filesystem, object storage, Git repositories, etc.

The protocol is ``runtime_checkable`` to support ``isinstance`` checks
for dependency injection and testing scenarios.

Usage
-----
Type-check a concrete adapter:

>>> from ghillie.reporting.sink import ReportSink
>>> from ghillie.reporting.filesystem_sink import FilesystemReportSink
>>> isinstance(FilesystemReportSink(Path(".")), ReportSink)
True

"""

from __future__ import annotations

import dataclasses as dc
import typing as typ


@dc.dataclass(frozen=True, slots=True)
class ReportMetadata:
    """Identifying metadata for a rendered report.

    Groups the report identification parameters into a single
    reusable object, reducing parameter counts on protocol methods
    and adapter implementations.

    Attributes
    ----------
    owner
        GitHub repository owner (organisation or user).
    name
        GitHub repository name.
    report_id
        Unique report identifier (UUID string).
    window_end
        ISO date string (YYYY-MM-DD) of the window end, used for
        the dated filename.

    """

    owner: str
    name: str
    report_id: str
    window_end: str


@typ.runtime_checkable
class ReportSink(typ.Protocol):
    """Protocol for writing rendered Markdown reports to storage.

    Implementations persist the rendered Markdown document at a
    predictable path so operators can navigate to a repository's
    latest report.

    """

    async def write_report(
        self,
        markdown: str,
        *,
        metadata: ReportMetadata,
    ) -> None:
        """Write a rendered Markdown report to storage.

        Parameters
        ----------
        markdown
            The rendered Markdown content.
        metadata
            Report identification metadata (owner, name, report_id,
            window_end).

        """
        ...
