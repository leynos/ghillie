"""Unit tests for local_k8s Kubernetes operations."""

from __future__ import annotations

import typing as typ

import pytest
from local_k8s.k8s import read_secret_field

if typ.TYPE_CHECKING:
    from cmd_mox import CmdMox


class TestReadSecretField:
    """Tests for read_secret_field validation and decoding."""

    @pytest.mark.parametrize(
        ("field", "kubectl_stdout", "expected"),
        [
            ("uri", "aGVsbG8=", "hello"),
            ("ca.crt", "Y2VydA==", "cert"),
            ("uri", "  aGVsbG8= \n", "hello"),
            ("Db_Url-Primary", "cG9zdGdyZXM6Ly9sb2NhbA==", "postgres://local"),
        ],
        ids=[
            "decodes-base64",
            "handles-dotted-field",
            "strips-whitespace",
            "accepts-valid-field-names",
        ],
    )
    def test_reads_and_decodes_secret_fields(  # noqa: PLR0913
        self,
        cmd_mox: CmdMox,
        test_env: dict[str, str],
        field: str,
        kubectl_stdout: str,
        expected: str,
    ) -> None:
        """Should read and decode secret fields for supported formats."""
        cmd_mox.mock("kubectl").with_args(
            "get",
            "secret",
            "my-secret",
            "--namespace=ghillie",
            "-o",
            f"jsonpath={{.data['{field}']}}",
        ).returns(stdout=kubectl_stdout, exit_code=0)

        actual = read_secret_field("my-secret", field, "ghillie", test_env)

        assert actual == expected

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
