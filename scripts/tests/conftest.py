"""Pytest configuration for scripts tests.

Adds the scripts directory to the Python path for imports.
The cmd-mox plugin is registered globally via pyproject.toml.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import os
import subprocess
import sys
import typing as typ
from pathlib import Path

import pytest

if typ.TYPE_CHECKING:
    from cyclopts import App

# Add scripts directory to path so we can import local_k8s
_scripts_dir = Path(__file__).resolve().parents[1]
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))


def load_script_app() -> App:
    """Load the app object from the local_k8s.py script.

    Since there is both a local_k8s/ package and a local_k8s.py script,
    Python's import system would prefer the package. This function loads
    the script directly using importlib.

    Returns:
        The Cyclopts App instance from local_k8s.py.

    """
    script_path = _scripts_dir / "local_k8s.py"
    spec = importlib.util.spec_from_file_location("local_k8s_script", script_path)
    if spec is None or spec.loader is None:
        msg = f"Could not load script from {script_path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.app


@pytest.fixture
def script_app() -> App:
    """Fixture that provides the local_k8s.py App for testing."""
    return load_script_app()


@pytest.fixture
def test_env(tmp_path: Path) -> dict[str, str]:
    """Create a test environment with a temporary KUBECONFIG path.

    Returns a copy of the current environment with KUBECONFIG pointing to
    a temporary file, allowing cmd-mox shims to work properly during testing.

    Args:
        tmp_path: Pytest's temporary path fixture.

    Returns:
        Environment dictionary with KUBECONFIG set to a temp file.

    """
    env = dict(os.environ)
    env["KUBECONFIG"] = str(tmp_path / "kubeconfig-test.yaml")
    return env


@dataclasses.dataclass(slots=True)
class MockSubprocessCapture:
    """Captured data from mocked subprocess.run calls."""

    calls: list[tuple[str, ...]]
    inputs: list[str]


@pytest.fixture
def mock_subprocess_run(
    monkeypatch: pytest.MonkeyPatch,
) -> MockSubprocessCapture:
    """Mock subprocess.run and return captured calls and inputs.

    Creates a mock that captures subprocess.run invocations and returns
    successful CompletedProcess results.

    Args:
        monkeypatch: Pytest's monkeypatch fixture.

    Returns:
        MockSubprocessCapture with calls list and inputs list.

    """
    import subprocess

    capture = MockSubprocessCapture(calls=[], inputs=[])

    def _mock_run(
        args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        capture.calls.append(tuple(args))
        if "input" in kwargs:
            capture.inputs.append(str(kwargs["input"]))
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="yaml-output"
        )

    monkeypatch.setattr("subprocess.run", _mock_run)
    return capture


SubprocessMockCallable = typ.Callable[[list[str]], subprocess.CompletedProcess[str]]


def make_subprocess_mock(
    calls: list[tuple[str, ...]],
    *,
    namespace_exists: bool = True,
    stdout: str = "",
) -> SubprocessMockCallable:
    """Create a subprocess.run mock that captures calls.

    Factory function to create a mock_run callable for use with monkeypatch.
    The mock captures all subprocess.run calls and returns CompletedProcess
    with configurable behaviour for namespace existence checks.

    Parameters
    ----------
    calls : list[tuple[str, ...]]
        List to append captured command tuples to.
    namespace_exists : bool, default True
        If False, kubectl get namespace commands return non-zero exit code.
    stdout : str, default ""
        Standard output to include in CompletedProcess.

    Returns
    -------
    Callable
        A mock_run function suitable for monkeypatch.setattr("subprocess.run", ...).

    Examples
    --------
    Mock subprocess with namespace not existing:

        calls = []
        mock_run = make_subprocess_mock(calls, namespace_exists=False)
        monkeypatch.setattr("subprocess.run", mock_run)

    """

    def mock_run(
        args: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(args))
        # Simulate namespace check: return non-zero if namespace_exists=False
        returncode = 0
        if not namespace_exists and args[:3] == ["kubectl", "get", "namespace"]:
            returncode = 1
        return subprocess.CompletedProcess(
            args=args, returncode=returncode, stdout=stdout
        )

    return mock_run
