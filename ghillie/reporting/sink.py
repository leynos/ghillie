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

import typing as typ


@typ.runtime_checkable
class ReportSink(typ.Protocol):
    """Protocol for writing rendered Markdown reports to storage.

    Implementations persist the rendered Markdown document at a
    predictable path so operators can navigate to a repository's
    latest report.

    """

    async def write_report(  # noqa: PLR0913
        self,
        markdown: str,
        *,
        owner: str,
        name: str,
        report_id: str,
        window_end: str,
    ) -> None:
        """Write a rendered Markdown report to storage.

        Parameters
        ----------
        markdown
            The rendered Markdown content.
        owner
            GitHub repository owner.
        name
            GitHub repository name.
        report_id
            Unique report identifier (UUID string).
        window_end
            ISO date string (YYYY-MM-DD) of the window end, used for
            the dated filename.

        """
        ...
