r"""Filesystem adapter for the ReportSink protocol.

Writes rendered Markdown reports to a local filesystem with a
predictable directory structure::

    {base_path}/{owner}/{name}/latest.md
    {base_path}/{owner}/{name}/{date}-{report_id}.md

Usage
-----
Create a sink and write a report:

>>> import asyncio
>>> from pathlib import Path
>>> from ghillie.reporting.filesystem_sink import FilesystemReportSink
>>>
>>> sink = FilesystemReportSink(Path("/var/lib/ghillie/reports"))
>>> asyncio.run(sink.write_report(
...     "# Report\n\nContent",
...     owner="acme",
...     name="widget",
...     report_id="abc-123",
...     window_end="2024-07-08",
... ))

"""

from __future__ import annotations

import asyncio
import typing as typ

if typ.TYPE_CHECKING:
    from pathlib import Path


class FilesystemReportSink:
    """Write reports to the local filesystem.

    Parameters
    ----------
    base_path
        Root directory for report storage. Subdirectories are created
        per ``{owner}/{name}``.

    """

    def __init__(self, base_path: Path) -> None:
        """Initialise the sink with a base directory path."""
        self._base_path = base_path

    async def write_report(  # noqa: PLR0913
        self,
        markdown: str,
        *,
        owner: str,
        name: str,
        report_id: str,
        window_end: str,
    ) -> None:
        """Write Markdown to ``latest.md`` and a dated archive file.

        Parameters
        ----------
        markdown
            Rendered Markdown content.
        owner
            GitHub repository owner.
        name
            GitHub repository name.
        report_id
            Report UUID for the dated filename.
        window_end
            ISO date (YYYY-MM-DD) for the dated filename.

        """
        repo_dir = self._base_path / owner / name
        await asyncio.to_thread(repo_dir.mkdir, parents=True, exist_ok=True)

        latest_path = repo_dir / "latest.md"
        dated_path = repo_dir / f"{window_end}-{report_id}.md"

        await asyncio.to_thread(latest_path.write_text, markdown, "utf-8")
        await asyncio.to_thread(dated_path.write_text, markdown, "utf-8")
