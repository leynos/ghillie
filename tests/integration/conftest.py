"""VidaiMock fixture for LLM integration testing.

This module provides a session-scoped pytest fixture that starts VidaiMock
as a subprocess for testing OpenAI-compatible LLM integrations.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import typing as typ
from contextlib import closing

import httpx
import pytest

if typ.TYPE_CHECKING:
    from pathlib import Path

    from ghillie.status.config import OpenAIStatusModelConfig

_HTTP_OK = 200

# Check if VidaiMock binary is available
_VIDAIMOCK_AVAILABLE = shutil.which("vidaimock") is not None

# VidaiMock configuration following ADR-002 structure.
# The response body content is a JSON string that will be returned as the
# assistant message content.
_STATUS_RESPONSE_CONTENT = json.dumps(
    {
        "status": "on_track",
        "summary": "Repository octo/reef shows healthy development activity with "
        "feature delivery on track.",
        "highlights": [
            "Feature PRs merged successfully",
            "Documentation updated",
        ],
        "risks": [],
        "next_steps": [
            "Continue current development velocity",
            "Review open PRs",
        ],
    }
)

VIDAIMOCK_CONFIG = f"""\
providers:
  - name: openai
    base_url: /v1
    endpoints:
      - path: /chat/completions
        method: POST
        response:
          status: 200
          body:
            id: "chatcmpl-mock-ghillie"
            object: "chat.completion"
            created: 1700000000
            model: "gpt-5.1-thinking"
            choices:
              - index: 0
                message:
                  role: "assistant"
                  content: {json.dumps(_STATUS_RESPONSE_CONTENT)}
                finish_reason: "stop"
            usage:
              prompt_tokens: 500
              completion_tokens: 100
              total_tokens: 600
"""


def _bind_ephemeral_port() -> int:
    """Bind to port 0 and return the assigned port.

    This reduces TOCTOU race likelihood by briefly binding to get a free port.

    Returns
    -------
    int
        An available port number.

    """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_server(url: str, *, timeout: float = 10.0) -> None:
    """Poll a health endpoint until it responds or timeout is exceeded.

    Parameters
    ----------
    url
        Health endpoint URL to poll.
    timeout
        Maximum seconds to wait for the server.

    Raises
    ------
    TimeoutError
        If the server does not become ready within the timeout.

    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=1.0)
            if response.status_code == _HTTP_OK:
                return
        except httpx.RequestError:
            pass
        time.sleep(0.1)
    msg = f"Server at {url} did not become ready within {timeout}s"
    raise TimeoutError(msg)


def _verify_vidaimock_config(base_url: str) -> bool:
    """Verify VidaiMock is returning configured responses, not defaults.

    Parameters
    ----------
    base_url
        Base URL of the VidaiMock server.

    Returns
    -------
    bool
        True if VidaiMock returns JSON-parseable content, False if generic.

    """
    try:
        response = httpx.post(
            f"{base_url}/v1/chat/completions",
            json={"model": "test", "messages": []},
            timeout=5.0,
        )
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        # Check if content is JSON (configured) vs generic text
        json.loads(content)
    except (httpx.RequestError, json.JSONDecodeError, KeyError, IndexError):
        return False
    else:
        return True


@pytest.fixture(scope="session")
def vidaimock_server(
    tmp_path_factory: pytest.TempPathFactory,
) -> typ.Iterator[str]:
    """Start VidaiMock server and yield its base URL.

    This fixture starts VidaiMock as a subprocess, waits for it to become
    healthy, and yields its base URL for tests to use. The subprocess is
    terminated when the test session ends.

    Yields
    ------
    str
        Base URL of the VidaiMock server (e.g., "http://127.0.0.1:12345").

    Raises
    ------
    pytest.skip
        If VidaiMock binary is not available.
    TimeoutError
        If VidaiMock does not become healthy within 10 seconds.

    """
    if not _VIDAIMOCK_AVAILABLE:
        pytest.skip("VidaiMock binary not found in PATH")

    port = _bind_ephemeral_port()
    config_dir: Path = tmp_path_factory.mktemp("vidaimock")
    config_path = config_dir / "config.yaml"
    config_path.write_text(VIDAIMOCK_CONFIG)

    # S603/S607: Command and args are test fixtures, not user input
    proc = subprocess.Popen(  # noqa: S603
        ["vidaimock", "--config", str(config_path), "--port", str(port)],  # noqa: S607
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_server(f"{base_url}/health", timeout=10)

        # Verify VidaiMock is using our config, not default responses
        if not _verify_vidaimock_config(base_url):
            proc.terminate()
            proc.wait(timeout=5)
            pytest.skip(
                "VidaiMock not returning configured responses "
                "(config loading may not be supported in this version)"
            )

        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@pytest.fixture
def openai_config_for_vidaimock(vidaimock_server: str) -> OpenAIStatusModelConfig:
    """Create OpenAI config pointing to VidaiMock server.

    Parameters
    ----------
    vidaimock_server
        Base URL of the running VidaiMock server.

    Returns
    -------
    OpenAIStatusModelConfig
        Configuration suitable for testing with VidaiMock.

    """
    from ghillie.status.config import OpenAIStatusModelConfig

    return OpenAIStatusModelConfig(
        api_key="test-api-key-for-vidaimock",
        endpoint=f"{vidaimock_server}/v1/chat/completions",
        model="gpt-5.1-thinking",
        timeout_s=30.0,
    )
