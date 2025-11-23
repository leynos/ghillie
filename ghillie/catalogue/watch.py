"""Watchers that trigger catalogue imports when the git repo changes."""

from __future__ import annotations

import asyncio
import dataclasses
import pathlib
import shutil
import subprocess
import typing as typ

from .importer import import_catalogue_job

if typ.TYPE_CHECKING:
    import dramatiq


@dataclasses.dataclass(slots=True)
class CatalogueWatcherConfig:
    """Configuration for git catalogue watching."""

    branch: str = "main"
    estate_key: str = "default"
    estate_name: str | None = None
    actor: dramatiq.Actor | None = None


class GitCatalogueWatcher:
    """Poll a git repository and enqueue catalogue imports when HEAD changes."""

    def __init__(
        self,
        repo_path: pathlib.Path,
        catalogue_relative_path: str,
        database_url: str,
        config: CatalogueWatcherConfig | None = None,
    ) -> None:
        """Initialise the watcher with repository location and actor."""
        watcher_config = config or CatalogueWatcherConfig()

        self.repo_path = pathlib.Path(repo_path)
        self.catalogue_relative_path = catalogue_relative_path
        self.database_url = database_url
        self.branch = watcher_config.branch
        self.estate_key = watcher_config.estate_key
        self.estate_name = watcher_config.estate_name
        self.actor = watcher_config.actor or import_catalogue_job
        self._last_seen: str | None = None

    def tick(self) -> bool:
        """Check for a new commit and enqueue an import if needed."""
        commit = self._current_commit()
        if commit == self._last_seen:
            return False

        catalogue_path = self.repo_path / self.catalogue_relative_path
        if not catalogue_path.exists():
            message = f"catalogue file {catalogue_path} does not exist"
            raise FileNotFoundError(message)

        self.actor.send(
            str(catalogue_path),
            self.database_url,
            commit_sha=commit,
            estate=(self.estate_key, self.estate_name),
        )
        self._last_seen = commit
        return True

    async def run(self, poll_interval: float = 30.0) -> None:
        """Run the watcher loop forever with the given poll interval."""
        while True:
            await self._tick_async()
            await asyncio.sleep(poll_interval)

    def _current_commit(self) -> str:
        """Return the HEAD commit for the configured branch."""
        git_executable = shutil.which("git")
        if git_executable is None:
            message = "git executable not found on PATH"
            raise FileNotFoundError(message)

        result = subprocess.run(  # noqa: S603  # fixed argv to local git repo only
            [git_executable, "-C", str(self.repo_path), "rev-parse", self.branch],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()

    async def _current_commit_async(self) -> str:
        """Resolve HEAD without blocking the event loop."""
        return await asyncio.to_thread(self._current_commit)

    async def _tick_async(self) -> bool:
        """Async variant of :meth:`tick`, offloading git calls to a thread."""
        commit = await self._current_commit_async()
        if commit == self._last_seen:
            return False

        catalogue_path = self.repo_path / self.catalogue_relative_path
        if not catalogue_path.exists():
            message = f"catalogue file {catalogue_path} does not exist"
            raise FileNotFoundError(message)

        self.actor.send(
            str(catalogue_path),
            self.database_url,
            commit_sha=commit,
            estate=(self.estate_key, self.estate_name),
        )
        self._last_seen = commit
        return True
