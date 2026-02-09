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
>>> from ghillie.reporting.sink import ReportMetadata
>>>
>>> sink = FilesystemReportSink(Path("/var/lib/ghillie/reports"))
>>> meta = ReportMetadata(
...     owner="acme",
...     name="widget",
...     report_id="abc-123",
...     window_end="2024-07-08",
... )
>>> asyncio.run(sink.write_report("# Report\n\nContent", metadata=meta))

"""

from __future__ import annotations

import asyncio
import typing as typ

if typ.TYPE_CHECKING:
    from pathlib import Path

    from ghillie.reporting.sink import ReportMetadata


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

    async def write_report(
        self,
        markdown: str,
        *,
        metadata: ReportMetadata,
    ) -> None:
        """Write Markdown to ``latest.md`` and a dated archive file.

        Parameters
        ----------
        markdown
            Rendered Markdown content.
        metadata
            Report identification metadata (owner, name, report_id,
            window_end).

        """
        repo_dir = self._base_path / metadata.owner / metadata.name
        await asyncio.to_thread(repo_dir.mkdir, parents=True, exist_ok=True)

        latest_path = repo_dir / "latest.md"
        dated_path = repo_dir / f"{metadata.window_end}-{metadata.report_id}.md"

        await asyncio.to_thread(latest_path.write_text, markdown, "utf-8")
        await asyncio.to_thread(dated_path.write_text, markdown, "utf-8")
