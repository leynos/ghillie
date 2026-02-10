"""Unit tests for FilesystemReportSink."""

from __future__ import annotations

import asyncio
import typing as typ

import pytest

from ghillie.reporting.filesystem_sink import FilesystemReportSink
from ghillie.reporting.sink import ReportMetadata

if typ.TYPE_CHECKING:
    from pathlib import Path


class TestFilesystemReportSink:
    """Tests for the filesystem report sink adapter."""

    @pytest.fixture
    def base_path(self, tmp_path: Path) -> Path:
        """Return a temporary base path for report storage."""
        return tmp_path / "reports"

    @pytest.fixture
    def sink(self, base_path: Path) -> FilesystemReportSink:
        """Return a FilesystemReportSink writing to the temp directory."""
        return FilesystemReportSink(base_path)

    def _write(
        self,
        sink: FilesystemReportSink,
        *,
        markdown: str = "# Test Report\n\nContent here.",
        metadata: ReportMetadata | None = None,
    ) -> None:
        """Run the async write_report synchronously.

        Parameters
        ----------
        sink
            The filesystem sink under test.
        markdown
            Rendered Markdown content to write.
        metadata
            Report metadata.  Defaults to standard test values
            (``acme/widget``, report ``rpt-001``, window end
            ``2024-07-08``).

        """
        effective = metadata or ReportMetadata(
            owner="acme",
            name="widget",
            report_id="rpt-001",
            window_end="2024-07-08",
        )
        asyncio.run(sink.write_report(markdown, metadata=effective))

    def test_write_creates_owner_name_directory(
        self, sink: FilesystemReportSink, base_path: Path
    ) -> None:
        """The sink creates {base_path}/{owner}/{name}/ directory."""
        self._write(sink)

        repo_dir = base_path / "acme" / "widget"
        assert repo_dir.is_dir(), "Sink should create owner/name directory structure"

    def test_write_creates_latest_md(
        self, sink: FilesystemReportSink, base_path: Path
    ) -> None:
        """A file latest.md is written at the expected path."""
        self._write(sink)

        latest = base_path / "acme" / "widget" / "latest.md"
        assert latest.is_file(), "latest.md should be created"

    def test_write_creates_dated_report(
        self, sink: FilesystemReportSink, base_path: Path
    ) -> None:
        """A dated file is written alongside latest.md."""
        self._write(sink)

        dated = base_path / "acme" / "widget" / "2024-07-08-rpt-001.md"
        assert dated.is_file(), "Dated report file should be created"

    def test_latest_md_content_matches_rendered_markdown(
        self, sink: FilesystemReportSink, base_path: Path
    ) -> None:
        """The content of latest.md matches the Markdown string."""
        content = "# Weekly Report\n\nEverything is fine."
        self._write(sink, markdown=content)

        latest = base_path / "acme" / "widget" / "latest.md"
        assert latest.read_text(encoding="utf-8") == content

    def test_write_overwrites_existing_latest(
        self, sink: FilesystemReportSink, base_path: Path
    ) -> None:
        """Writing a new report replaces the existing latest.md."""
        self._write(sink, markdown="Old report")
        self._write(
            sink,
            markdown="New report",
            metadata=ReportMetadata(
                owner="acme",
                name="widget",
                report_id="rpt-002",
                window_end="2024-07-08",
            ),
        )

        latest = base_path / "acme" / "widget" / "latest.md"
        assert latest.read_text(encoding="utf-8") == "New report"

    def test_dated_reports_accumulate(
        self, sink: FilesystemReportSink, base_path: Path
    ) -> None:
        """Multiple writes produce multiple dated files."""
        self._write(
            sink,
            markdown="First",
            metadata=ReportMetadata(
                owner="acme",
                name="widget",
                report_id="rpt-001",
                window_end="2024-07-01",
            ),
        )
        self._write(
            sink,
            markdown="Second",
            metadata=ReportMetadata(
                owner="acme",
                name="widget",
                report_id="rpt-002",
                window_end="2024-07-08",
            ),
        )

        repo_dir = base_path / "acme" / "widget"
        dated_files = sorted(f for f in repo_dir.iterdir() if f.name != "latest.md")
        assert len(dated_files) == 2, "Two dated report files should exist"
        assert dated_files[0].name == "2024-07-01-rpt-001.md"
        assert dated_files[1].name == "2024-07-08-rpt-002.md"
