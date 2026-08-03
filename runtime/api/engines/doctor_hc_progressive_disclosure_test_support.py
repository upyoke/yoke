"""Shared fixtures for progressive-disclosure direction tests."""

from pathlib import Path
from typing import Dict, Iterable, Iterator, Tuple

import pytest

from yoke_project_checks import check_progressive_disclosure_direction as mod
from yoke_project_checks.check_progressive_disclosure_direction import (
    hc_progressive_disclosure_direction,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_CONDUCT_SKILL = ".agents/skills/yoke/conduct/SKILL.md"
_ENGINEER_AGENT = "runtime/agents/engineer.md"
_ARCHITECT_AGENT = "runtime/agents/architect.md"
_FN_INVENTORY = "docs/atlas.md"


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


def _setup(tmp_path, monkeypatch, files, tier_for):
    _materialize(tmp_path, files)
    _install_iter(monkeypatch, tmp_path, tier_for)


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_progressive_disclosure_direction(conn, DoctorArgs(), rec)
    return rec


def _detail(rec: RecordCollector) -> str:
    return rec.results[0].detail
