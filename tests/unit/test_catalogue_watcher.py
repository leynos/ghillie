"""Unit tests for the git-based catalogue watcher."""

from __future__ import annotations

import shutil
import subprocess
import typing as typ

import dramatiq
import pytest
from dramatiq.brokers.stub import StubBroker
from dramatiq.message import Message

from ghillie.catalogue.watch import CatalogueWatcherConfig, GitCatalogueWatcher

if typ.TYPE_CHECKING:
    import pathlib


def _init_repo(repo_path: pathlib.Path) -> str:
    git_executable = shutil.which("git")
    if git_executable is None:
        message = "git binary required for watcher tests"
        raise FileNotFoundError(message)

    subprocess.run(  # noqa: S603  # fixed git init in local temp repo
        [git_executable, "init", str(repo_path)],
        check=True,
        capture_output=True,
        timeout=5,
    )
    subprocess.run(  # noqa: S603  # fixed git config
        [
            git_executable,
            "-C",
            str(repo_path),
            "config",
            "user.email",
            "ghillie@example.com",
        ],
        check=True,
        capture_output=True,
        timeout=5,
    )
    subprocess.run(  # noqa: S603  # fixed git config
        [git_executable, "-C", str(repo_path), "config", "user.name", "Ghillie"],
        check=True,
        capture_output=True,
        timeout=5,
    )
    subprocess.run(  # noqa: S603  # fixed git checkout
        [git_executable, "-C", str(repo_path), "checkout", "-b", "main"],
        check=True,
        capture_output=True,
        timeout=5,
    )
    (repo_path / "catalogue.yaml").write_text(
        """
version: 1
projects:
  - key: alpha
    name: Alpha
    components: []
""",
        encoding="utf-8",
    )
    subprocess.run(  # noqa: S603  # fixed git add
        [git_executable, "-C", str(repo_path), "add", "catalogue.yaml"],
        check=True,
        capture_output=True,
        timeout=5,
    )
    subprocess.run(  # noqa: S603  # fixed git commit
        [git_executable, "-C", str(repo_path), "commit", "-m", "init"],
        check=True,
        capture_output=True,
        timeout=5,
    )
    commit = subprocess.run(  # noqa: S603  # fixed git rev-parse
        [git_executable, "-C", str(repo_path), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return commit.stdout.strip()


@pytest.fixture(autouse=True)
def stub_broker() -> StubBroker:
    """Provide a stub Dramatiq broker for watcher tests."""
    broker = StubBroker()
    dramatiq.set_broker(broker)
    return broker


def test_watcher_enqueues_on_new_commit(  # noqa: D103
    tmp_path: pathlib.Path, stub_broker: StubBroker
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    commit = _init_repo(repo_path)

    broker = stub_broker

    @dramatiq.actor(broker=broker)
    def fake_import(catalogue_path: str, database_url: str, **_: object) -> None:
        return None

    config = CatalogueWatcherConfig(branch="main", actor=fake_import)
    watcher = GitCatalogueWatcher(
        repo_path,
        "catalogue.yaml",
        "sqlite:///example.db",
        config=config,
    )

    first = watcher.tick()
    assert first is True, "tick should enqueue on first unseen commit"

    queue = broker.queues[fake_import.queue_name]
    assert queue.qsize() == 1, "queue should have one message after first tick"
    decoded = Message.decode(queue.get_nowait())
    assert decoded.kwargs["commit_sha"] == commit, (
        "enqueued message should carry commit sha"
    )

    second = watcher.tick()
    assert second is False, "tick should not enqueue when commit unchanged"
    assert queue.qsize() == 0, "queue should be empty after reading the only message"
