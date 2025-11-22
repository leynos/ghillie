"""Unit tests for the git-based catalogue watcher."""
# ruff: noqa: D103,S603,S607

from __future__ import annotations

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
    subprocess.run(["git", "init", str(repo_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.email", "ghillie@example.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "config", "user.name", "Ghillie"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "checkout", "-b", "main"],
        check=True,
        capture_output=True,
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
    subprocess.run(
        ["git", "-C", str(repo_path), "add", "catalogue.yaml"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    )
    return commit.stdout.strip()


@pytest.fixture(autouse=True)
def stub_broker() -> StubBroker:
    broker = StubBroker()
    dramatiq.set_broker(broker)
    return broker


def test_watcher_enqueues_on_new_commit(
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
    assert first is True

    queue = broker.queues[fake_import.queue_name]
    assert queue.qsize() == 1
    decoded = Message.decode(queue.get_nowait())
    assert decoded.kwargs["commit_sha"] == commit

    second = watcher.tick()
    assert second is False
    assert queue.qsize() == 0
