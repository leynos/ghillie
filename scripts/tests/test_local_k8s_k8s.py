"""Unit tests for local_k8s Kubernetes operations."""

from __future__ import annotations

import typing as typ

import pytest
from local_k8s.k8s import read_secret_field

if typ.TYPE_CHECKING:
    from cmd_mox import CmdMox


class TestReadSecretField:
    """Tests for read_secret_field validation and decoding."""

    def test_decodes_base64_secret(
        self, cmd_mox: CmdMox, test_env: dict[str, str]
    ) -> None:
        """Should decode base64-encoded secret value."""
        # "secretvalue" base64 encoded
        encoded = "c2VjcmV0dmFsdWU="

        cmd_mox.mock("kubectl").with_args(
            "get",
            "secret",
            "my-secret",
            "--namespace=ghillie",
            "-o",
            "jsonpath={.data['password']}",
        ).returns(exit_code=0, stdout=encoded)

        result = read_secret_field("my-secret", "password", "ghillie", test_env)

        assert result == "secretvalue"

    def test_handles_dotted_field_names(
        self, cmd_mox: CmdMox, test_env: dict[str, str]
    ) -> None:
        """Should handle dotted field names like ca.crt."""
        # "cert-data" base64 encoded
        encoded = "Y2VydC1kYXRh"

        cmd_mox.mock("kubectl").with_args(
            "get",
            "secret",
            "tls-secret",
            "--namespace=ghillie",
            "-o",
            "jsonpath={.data['ca.crt']}",
        ).returns(exit_code=0, stdout=encoded)

        result = read_secret_field("tls-secret", "ca.crt", "ghillie", test_env)

        assert result == "cert-data"

    def test_raises_on_empty_field(self, test_env: dict[str, str]) -> None:
        """Should raise ValueError when field is empty."""
        with pytest.raises(ValueError, match="field cannot be empty"):
            read_secret_field("my-secret", "", "ghillie", test_env)

    @pytest.mark.parametrize(
        ("field", "error_match"),
        [
            ("password'", "invalid characters"),
            ("field]name", "invalid characters"),
            ("field[0]", "invalid characters"),
            ("has space", "invalid characters"),
            ("has@symbol", "invalid characters"),
        ],
    )
    def test_raises_on_invalid_field_characters(
        self, field: str, error_match: str, test_env: dict[str, str]
    ) -> None:
        """Should raise ValueError when field contains invalid characters."""
        with pytest.raises(ValueError, match=error_match):
            read_secret_field("my-secret", field, "ghillie", test_env)

    @pytest.mark.parametrize(
        "field",
        [
            "password",
            "DATABASE_URL",
            "ca.crt",
            "my-key",
            "key_name",
            "field.with.dots",
            "MixedCase123",
        ],
    )
    def test_accepts_valid_field_names(
        self, cmd_mox: CmdMox, field: str, test_env: dict[str, str]
    ) -> None:
        """Should accept valid Kubernetes secret key names."""
        # "test" base64 encoded
        encoded = "dGVzdA=="

        cmd_mox.mock("kubectl").with_args(
            "get",
            "secret",
            "my-secret",
            "--namespace=ghillie",
            "-o",
            f"jsonpath={{.data['{field}']}}",
        ).returns(exit_code=0, stdout=encoded)

        result = read_secret_field("my-secret", field, "ghillie", test_env)

        assert result == "test"

    def test_raises_on_empty_output(
        self, cmd_mox: CmdMox, test_env: dict[str, str]
    ) -> None:
        """Should raise ValueError when kubectl returns empty output."""
        cmd_mox.mock("kubectl").with_args(
            "get",
            "secret",
            "my-secret",
            "--namespace=ghillie",
            "-o",
            "jsonpath={.data['password']}",
        ).returns(exit_code=0, stdout="")

        with pytest.raises(ValueError, match="empty or missing"):
            read_secret_field("my-secret", "password", "ghillie", test_env)

    def test_strips_whitespace_from_output(
        self, cmd_mox: CmdMox, test_env: dict[str, str]
    ) -> None:
        """Should strip whitespace from kubectl output before decoding."""
        # "value" base64 encoded, with trailing whitespace
        encoded = "dmFsdWU=\n  "

        cmd_mox.mock("kubectl").with_args(
            "get",
            "secret",
            "my-secret",
            "--namespace=ghillie",
            "-o",
            "jsonpath={.data['key']}",
        ).returns(exit_code=0, stdout=encoded)

        result = read_secret_field("my-secret", "key", "ghillie", test_env)

        assert result == "value"
