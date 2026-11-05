"""Fixtures and helpers for end-to-end tests of the packaged runtime.

The server runs as its own process with a SQLite database and the opt-in
bootstrap enabled. The CLI under test runs as a child process too, so these
tests exercise the real console entry points rather than in-process calls.
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import signal
import socket
import subprocess
import sys
import time
import typing as typ
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_STARTUP_TIMEOUT_S = 20.0
_STARTUP_ATTEMPTS = 3
_POLL_INTERVAL_S = 0.1
_SHUTDOWN_TIMEOUT_S = 10.0
_REQUEST_TIMEOUT_S = 5.0

_CLI_ENVIRONMENT = (
    "GHILLIE_API_BASE_URL",
    "GHILLIE_API_TOKEN",
    "GHILLIE_AUTH_TOKEN",
    "GHILLIE_DRY_RUN",
    "GHILLIE_LOG_LEVEL",
    "GHILLIE_NON_INTERACTIVE",
    "GHILLIE_OUTPUT",
    "GHILLIE_REQUEST_TIMEOUT_S",
)

_SERVER_ENVIRONMENT = (
    "GHILLIE_STATUS_MODEL_BACKEND",
    "GHILLIE_ALLOW_STUB_BROKER",
)


@dataclasses.dataclass(frozen=True)
class GhillieServer:
    """A running Ghillie process and the paths its children share."""

    base_url: str
    home: Path
    log_path: Path
    process: subprocess.Popen[bytes]

    def log_text(self) -> str:
        """Return the captured server log."""
        return self.log_path.read_text(encoding="utf-8", errors="replace")


@dataclasses.dataclass(frozen=True)
class CliResult:
    """Captured result of one CLI invocation."""

    returncode: int
    stdout: str
    stderr: str

    def detail(self) -> str:
        """Return the streams for a failing assertion message."""
        return f"exit={self.returncode}\nstdout:\n{self.stdout}\nstderr:\n{self.stderr}"


def _find_free_port() -> int:
    """Return a currently free TCP port on the loopback interface."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _child_environment(home: Path, port: int, database: Path) -> dict[str, str]:
    """Build a deterministic environment for a server or CLI child."""
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("PYTEST_")
    }
    for name in (*_CLI_ENVIRONMENT, *_SERVER_ENVIRONMENT):
        env.pop(name, None)
    env.update(
        {
            "HOME": str(home),
            "GHILLIE_ALLOW_STUB_BROKER": "1",
            "GHILLIE_DATABASE_URL": f"sqlite+aiosqlite:///{database}",
            "GHILLIE_DB_BOOTSTRAP": "create-all",
            "GHILLIE_HOST": "127.0.0.1",
            "GHILLIE_PORT": str(port),
        }
    )
    return env


def run_cli(
    server: GhillieServer,
    *arguments: str,
    executable: typ.Sequence[str] | None = None,
) -> CliResult:
    """Run the CLI against *server* and capture its streams."""
    command = list(executable or [sys.executable, "-m", "ghillie.cli"])
    command += ["--api-base-url", server.base_url, *arguments]
    home = server.home
    env = _child_environment(
        home, int(server.base_url.rsplit(":", 1)[1]), home / "cli.db"
    )
    completed = subprocess.run(  # noqa: S603 - arguments are test-controlled
        command,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return CliResult(completed.returncode, completed.stdout, completed.stderr)


def _wait_until_serving(process: subprocess.Popen[bytes], base_url: str) -> None:
    """Poll ``GET /estates`` until the service answers with an empty page."""
    deadline = time.monotonic() + _STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if process.poll() is not None:
            message = f"server exited with code {process.returncode}"
            raise RuntimeError(message)
        try:
            response = httpx.get(f"{base_url}/estates", timeout=_REQUEST_TIMEOUT_S)
        except httpx.HTTPError:
            time.sleep(_POLL_INTERVAL_S)
            continue
        if (
            response.status_code == httpx.codes.OK
            and response.json().get("items") == []
        ):
            return
        time.sleep(_POLL_INTERVAL_S)
    message = f"timed out waiting for {base_url}/estates"
    raise RuntimeError(message)


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Stop *process* and its process group, escalating to SIGKILL."""
    if process.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    try:
        process.wait(timeout=_SHUTDOWN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        process.wait(timeout=_SHUTDOWN_TIMEOUT_S)


def _start_server(tmp_path: Path) -> GhillieServer:
    """Start a server, retrying on a fresh port if it exits immediately."""
    last_error: Exception | None = None
    for attempt in range(_STARTUP_ATTEMPTS):
        port = _find_free_port()
        home = tmp_path / f"home-{attempt}"
        home.mkdir()
        database = tmp_path / f"ghillie-{attempt}.db"
        env = _child_environment(home, port, database)
        log_path = tmp_path / f"server-{attempt}.log"
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "ghillie.runtime"],
                cwd=REPO_ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        base_url = f"http://127.0.0.1:{port}"
        try:
            _wait_until_serving(process, base_url)
        except RuntimeError as exc:
            last_error = exc
            _stop(process)
            continue
        return GhillieServer(base_url, home, log_path, process)
    message = f"could not start the Ghillie runtime after {_STARTUP_ATTEMPTS} attempts"
    raise RuntimeError(message) from last_error


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo[typ.Any],
) -> typ.Generator[None, object]:
    """Record each phase report so the server fixture can inspect failures."""
    outcome: typ.Any = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture
def ghillie_server(
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> typ.Iterator[GhillieServer]:
    """Start a Ghillie runtime for one test and stop it afterwards."""
    server = _start_server(tmp_path)
    try:
        yield server
    finally:
        _stop(server.process)
        report = getattr(request.node, "rep_call", None)
        if report is not None and report.failed:
            print(server.log_text(), file=sys.stderr)
