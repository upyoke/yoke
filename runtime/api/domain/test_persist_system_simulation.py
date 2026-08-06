"""Clean-checkout coverage for system-simulation report persistence."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from yoke_core.domain.persist_system_simulation import (
    default_report_path,
    persist_system_simulation_report,
)


def test_first_run_creates_health_dir_on_clean_checkout(tmp_path: Path) -> None:
    """A checkout with no ``ouroboros/health`` still persists the report."""
    assert not (tmp_path / "ouroboros").exists()
    body = "SIMULATION: CLEAN\nSCOPE: SYSTEM\n"
    day = date(2026, 8, 5)

    out = persist_system_simulation_report(body, repo_root=tmp_path, day=day)

    assert out == tmp_path / "ouroboros" / "health" / "simulation-system-20260805.md"
    assert out.is_file()
    assert out.read_text(encoding="utf-8") == body
    assert out.parent.is_dir()


def test_default_report_path_uses_dated_filename(tmp_path: Path) -> None:
    day = date(2026, 1, 2)
    assert default_report_path(tmp_path, day=day) == (
        tmp_path / "ouroboros" / "health" / "simulation-system-20260102.md"
    )


def test_explicit_path_still_creates_missing_parents(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "out" / "report.md"
    assert not target.parent.exists()

    out = persist_system_simulation_report("body\n", path=target)

    assert out == target
    assert out.read_text(encoding="utf-8") == "body\n"
