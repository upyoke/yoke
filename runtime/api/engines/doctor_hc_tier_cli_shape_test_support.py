"""Shared fixtures for tier CLI-shape tests."""

from pathlib import Path
from typing import Dict, Iterable, Iterator, Tuple

import pytest

from yoke_project_checks import check_tier_cli_shape_bleed as mod
from yoke_project_checks.check_tier_cli_shape_bleed import (
    hc_tier_cli_shape_bleed,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


@pytest.fixture
def conn():
    """The HC under test scans tier files only; it never reads *conn*."""
    return None


def _materialize(tmp_path: Path, files: Dict[str, str]) -> Path:
    for rel, content in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


def _install_iter(
    monkeypatch: pytest.MonkeyPatch,
    repo_root: Path,
    tier_for: Dict[str, int],
) -> None:
    def fake_iter(
        repo: Path, tiers: Iterable[int] = (0, 2, 4, 5)
    ) -> Iterator[Tuple[int, Path]]:
        tier_set = set(tiers)
        for rel, tier in sorted(tier_for.items()):
            if tier in tier_set:
                yield tier, repo_root / rel

    monkeypatch.setattr(mod, "iter_tier_paths", fake_iter)
    monkeypatch.setattr(mod, "_resolve_repo_root", lambda: str(repo_root))


def _install_help_table(
    monkeypatch: pytest.MonkeyPatch,
    table: Dict[Tuple[str, object], Tuple[int, str]],
) -> None:
    def fake_run_help(_repo_root, module, sub):
        return table.get((module, sub), (1, ""))

    monkeypatch.setattr(mod, "_run_help", fake_run_help)


def _setup(tmp_path, monkeypatch, files, tier_for, help_table=None):
    _materialize(tmp_path, files)
    _install_iter(monkeypatch, tmp_path, tier_for)
    _install_help_table(monkeypatch, help_table or {})


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_tier_cli_shape_bleed(conn, DoctorArgs(), rec)
    return rec


def _detail(rec: RecordCollector) -> str:
    return rec.results[0].detail


# --- Check A: CLI shape drift (argparse-help-driven) ----------------------
