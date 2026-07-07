"""Tests for HC-skill-recipe-execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.engines.doctor_hc_skill_recipe_execution import (
    hc_skill_recipe_execution,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _make_args(quick: bool = False) -> DoctorArgs:
    return DoctorArgs(quick=quick)


def _run(skill_root: Path, *, quick: bool = False) -> RecordCollector:
    args = _make_args(quick=quick)
    rec = RecordCollector()
    import os
    prior = os.environ.get("YOKE_SKILL_ROOT")
    os.environ["YOKE_SKILL_ROOT"] = str(skill_root)
    try:
        hc_skill_recipe_execution(None, args, rec)
    finally:
        if prior is None:
            os.environ.pop("YOKE_SKILL_ROOT", None)
        else:
            os.environ["YOKE_SKILL_ROOT"] = prior
    return rec


class TestHcSkillRecipeExecution:
    def test_skill_root_missing_self_skips(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope"
        rec = _run(missing)
        assert len(rec.results) == 1
        assert rec.results[0].result == "PASS"
        assert "self-skipped" in rec.results[0].detail

    def test_empty_skill_root_passes_with_note(self, tmp_path: Path) -> None:
        skill_root = tmp_path / "skills"
        skill_root.mkdir()
        rec = _run(skill_root)
        assert rec.results[0].result == "PASS"
        assert "no yoke <subcommand> recipes" in rec.results[0].detail

    def test_all_recipes_pass(self, tmp_path: Path) -> None:
        skill_root = tmp_path / "skills"
        skill_root.mkdir()
        (skill_root / "a.md").write_text(
            "```bash\nyoke items get YOK-1\n```\n", encoding="utf-8",
        )
        (skill_root / "b.md").write_text(
            "```bash\nyoke items get YOK-2\n```\n", encoding="utf-8",
        )
        rec = _run(skill_root)
        assert rec.results[0].result == "PASS"
        assert "full sweep" in rec.results[0].detail
        assert "2 recipes" in rec.results[0].detail

    def test_failure_reports_first_failures(self, tmp_path: Path) -> None:
        skill_root = tmp_path / "skills"
        skill_root.mkdir()
        (skill_root / "bad.md").write_text(
            "```bash\nyoke nope nope\nyoke items get YOK-1\n```\n",
            encoding="utf-8",
        )
        rec = _run(skill_root)
        assert rec.results[0].result == "FAIL"
        assert "yoke nope nope" in rec.results[0].detail

    def test_quick_mode_samples(self, tmp_path: Path) -> None:
        # Build 5 recipes in one md file; quick mode caps at 3 per directory.
        skill_root = tmp_path / "skills"
        skill_root.mkdir()
        recipes = "\n".join(f"yoke items get YOK-{i}" for i in range(1, 6))
        (skill_root / "many.md").write_text(
            f"```bash\n{recipes}\n```\n", encoding="utf-8",
        )
        rec = _run(skill_root, quick=True)
        assert rec.results[0].result == "PASS"
        assert "quick sample" in rec.results[0].detail
        assert "3 of 5" in rec.results[0].detail
