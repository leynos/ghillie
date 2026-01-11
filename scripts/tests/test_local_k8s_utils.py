"""Unit tests for local_k8s utility functions."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from local_k8s import ExecutableNotFoundError
from local_k8s.validation import (
    b64decode_k8s_secret_field,
    pick_free_loopback_port,
    require_exe,
)


class TestRequireExe:
    """Tests for require_exe helper."""

    def test_succeeds_for_available_executable(self) -> None:
        """require_exe should not raise for an existing executable."""
        # Derive a portable executable name from the running interpreter
        exe_name = Path(sys.executable).name
        if not shutil.which(exe_name):
            pytest.skip(f"No suitable Python executable '{exe_name}' found on PATH")
        require_exe(exe_name)

    def test_raises_for_missing_executable(self) -> None:
        """require_exe should raise ExecutableNotFoundError for missing exe."""
        with pytest.raises(ExecutableNotFoundError) as exc_info:
            require_exe("definitely_not_a_real_executable_xyz_123")

        assert "definitely_not_a_real_executable_xyz_123" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()


class TestPickFreeLoopbackPort:
    """Tests for pick_free_loopback_port helper."""

    def test_returns_valid_port(self) -> None:
        """Should return a port number in the valid range."""
        port = pick_free_loopback_port()

        # Ephemeral ports are typically 1024-65535, but we got it from the OS
        assert 1 <= port <= 65535


class TestB64DecodeK8sSecretField:
    """Tests for base64 decoding helper."""

    def test_decodes_hello(self) -> None:
        """Should decode 'hello' correctly."""
        # "hello" in base64 is "aGVsbG8="
        assert b64decode_k8s_secret_field("aGVsbG8=") == "hello"

    def test_decodes_database_url(self) -> None:
        """Should decode a typical database URL."""
        # "postgresql://user:pass@localhost:5432/db" in base64
        encoded = "cG9zdGdyZXNxbDovL3VzZXI6cGFzc0Bsb2NhbGhvc3Q6NTQzMi9kYg=="
        expected = "postgresql://user:pass@localhost:5432/db"

        assert b64decode_k8s_secret_field(encoded) == expected

    def test_decodes_empty_string(self) -> None:
        """Should decode empty base64 to empty string."""
        assert b64decode_k8s_secret_field("") == ""

    def test_decodes_unicode(self) -> None:
        """Should decode UTF-8 content correctly."""
        # "café" in base64
        encoded = "Y2Fmw6k="
        assert b64decode_k8s_secret_field(encoded) == "café"
