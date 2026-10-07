"""Tests for HC-project-name-literal."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_project_name_literal as hc

_CHECK_ID = "HC-project-name-literal"


def _run(root: Path) -> RecordCollector:
    rec = RecordCollector()
    args = DoctorArgs(file=None, fix=False, only=None, quick=False, project="p", db_path="")
    with mock.patch.object(hc, "_resolve_repo_root", return_value=str(root)):
        hc.hc_project_name_literal(None, args, rec)
    return rec


def _record(rec: RecordCollector):
    matches = [row for row in rec.results if row.check_id == _CHECK_ID]
    assert len(matches) == 1
    return matches[0]


def test_clean_tree_passes(tmp_path: Path) -> None:
    module = tmp_path / "packages" / "pkg" / "src" / "pkg" / "clean.py"
    module.parent.mkdir(parents=True)
    module.write_text("def f(project):\n    return project\n", encoding="utf-8")

    assert _record(_run(tmp_path)).result == "PASS"


def test_project_name_branch_fails_with_location_and_recovery(tmp_path: Path) -> None:
    module = tmp_path / "packages" / "pkg" / "src" / "pkg" / "branch.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        'def f(args):\n    if args.project == "acme":\n        return 1\n',
        encoding="utf-8",
    )

    record = _record(_run(tmp_path))

    assert record.result == "FAIL"
    assert "project_name_literal_branch" in record.detail
    assert "packages/pkg/src/pkg/branch.py:2" in record.detail
    assert "Recovery:" in record.detail


def test_live_tree_has_no_project_name_branches() -> None:
    root = Path(__file__).resolve().parents[3]

    record = _record(_run(root))

    assert record.result == "PASS", record.detail
