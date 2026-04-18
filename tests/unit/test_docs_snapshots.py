"""Snapshot tests that guard high-signal ADR and ExecPlan documents."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_adr_001_snapshot(snapshot: object) -> None:
    """Keep ADR 001 content stable unless intentionally updated."""
    content = (
        _REPO_ROOT / "docs" / "adr-001-adoption-of-femtologging-library.md"
    ).read_text(encoding="utf-8")
    assert content == snapshot


def test_femtologging_execplan_snapshot(snapshot: object) -> None:
    """Keep the femtologging migration ExecPlan stable unless updated."""
    content = (
        _REPO_ROOT / "docs" / "execplans" / "femtologging-april-2026-migration.md"
    ).read_text(encoding="utf-8")
    assert content == snapshot
