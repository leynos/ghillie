"""Unit tests for the ``check_architecture`` Hecate compatibility wrapper.

The wrapper exists because the pinned Hecate commit constructs
``cyclopts.App`` with a ``result_action`` keyword that Ghillie's supported
Cyclopts range does not accept. Importing ``hecate`` (and therefore
``hecate.cli``) fails outside the compatibility patch, so the few tests that
need ``hecate.cli`` load it via the ``hecate_cli`` fixture, which imports the
module *inside* the patched context and skips when Hecate is not installed.
"""

from __future__ import annotations

import typing as typ
from unittest import mock

import check_architecture
import cyclopts
import pytest

if typ.TYPE_CHECKING:
    from types import ModuleType


@pytest.fixture
def hecate_cli() -> ModuleType:
    """Load ``hecate.cli`` under the compatibility patch.

    Importing ``hecate`` without the patch raises ``TypeError`` because of the
    unsupported ``result_action`` keyword, so the import is performed inside
    :func:`check_architecture._patched_cyclopts_app`. When Hecate is not
    installed the import raises ``ModuleNotFoundError`` and the test is
    skipped.
    """
    with check_architecture._patched_cyclopts_app():
        return pytest.importorskip("hecate.cli")


class TestCompatApp:
    """Tests for the ``_compat_app`` constructor shim."""

    def test_compat_app_removes_result_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``result_action`` is stripped while other keywords pass through."""
        captured = mock.MagicMock()
        monkeypatch.setattr(check_architecture, "_OriginalApp", captured)

        check_architecture._compat_app(result_action="ignored", name="hecate")

        captured.assert_called_once()
        _, kwargs = captured.call_args
        assert "result_action" not in kwargs, "result_action must not be forwarded"
        assert kwargs["name"] == "hecate", "other keywords must be forwarded"

    def test_compat_app_passes_positional_args(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Positional arguments reach the underlying constructor unchanged."""
        captured = mock.MagicMock()
        monkeypatch.setattr(check_architecture, "_OriginalApp", captured)

        check_architecture._compat_app("alpha", "beta")

        captured.assert_called_once()
        args, _ = captured.call_args
        assert args == ("alpha", "beta"), "positional args must be forwarded unchanged"

    def test_compat_app_no_result_action_is_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without ``result_action`` the keywords are forwarded intact."""
        captured = mock.MagicMock()
        monkeypatch.setattr(check_architecture, "_OriginalApp", captured)

        check_architecture._compat_app(name="hecate", help="docs")

        captured.assert_called_once()
        _, kwargs = captured.call_args
        assert kwargs == {"name": "hecate", "help": "docs"}, (
            "keywords must be forwarded intact"
        )


class TestPatchedCycloptsApp:
    """Tests for the ``_patched_cyclopts_app`` context manager."""

    def test_patched_cyclopts_app_installs_compat(self) -> None:
        """Inside the context ``cyclopts.App`` is the compatibility shim."""
        with check_architecture._patched_cyclopts_app():
            assert cyclopts.App is check_architecture._compat_app, (
                "compat constructor should be installed inside the context"
            )

    def test_patched_cyclopts_app_restores_original(self) -> None:
        """After a normal exit ``cyclopts.App`` is restored."""
        with check_architecture._patched_cyclopts_app():
            pass

        assert cyclopts.App is check_architecture._OriginalApp, (
            "original App should be restored after the context exits"
        )

    def test_patched_cyclopts_app_restores_on_exception(self) -> None:
        """``cyclopts.App`` is restored even when the body raises."""
        sentinel = RuntimeError("boom")
        with (
            pytest.raises(RuntimeError, match="boom"),
            check_architecture._patched_cyclopts_app(),
        ):
            raise sentinel

        assert cyclopts.App is check_architecture._OriginalApp, (
            "original App should be restored after an exception"
        )


class TestMain:
    """Tests for the ``main`` entry point."""

    def test_main_calls_hecate_with_correct_args(
        self, monkeypatch: pytest.MonkeyPatch, hecate_cli: ModuleType
    ) -> None:
        """``main`` invokes the Hecate CLI with the repository defaults."""
        hecate_main = mock.MagicMock(return_value=0)
        monkeypatch.setattr(hecate_cli, "main", hecate_main)

        check_architecture.main()

        hecate_main.assert_called_once_with(
            ["check", "--show-ignored", "--fail-on-unmatched-ignore"]
        )

    def test_main_returns_hecate_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, hecate_cli: ModuleType
    ) -> None:
        """``main`` returns the Hecate CLI exit code verbatim."""
        monkeypatch.setattr(hecate_cli, "main", mock.MagicMock(return_value=42))

        assert check_architecture.main() == 42, "exit code must be propagated"

    def test_main_restores_cyclopts_after_hecate_call(
        self, monkeypatch: pytest.MonkeyPatch, hecate_cli: ModuleType
    ) -> None:
        """``cyclopts.App`` is restored once ``main`` returns."""
        monkeypatch.setattr(hecate_cli, "main", mock.MagicMock(return_value=0))

        check_architecture.main()

        assert cyclopts.App is check_architecture._OriginalApp, (
            "original App should be restored after main runs"
        )
