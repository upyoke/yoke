"""Tests for HC-project-name-literal."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from yoke_core.domain.lint_project_name_literal_allowances import Allowance
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_project_name_literal as hc

_CHECK_ID = "HC-project-name-literal"
_LIVE_NAMES = frozenset({"yoke", "platform", "buzz"})


def _run(root, names=frozenset({"acme"}), allowances=()) -> RecordCollector:
    rec = RecordCollector()
    real_classify = hc.classify

    def classify(hits):
        if allowances is None:
            return real_classify(hits)
        return real_classify(hits, allowances)

    with (
        mock.patch.object(
            hc, "_resolve_repo_root", return_value=str(root) if root else None
        ),
        mock.patch.object(hc, "_project_names", return_value=frozenset(names)),
        mock.patch.object(hc, "classify", side_effect=classify),
    ):
        hc.hc_project_name_literal(None, DoctorArgs(project="p"), rec)
    return rec


def _record(rec: RecordCollector):
    matches = [row for row in rec.results if row.check_id == _CHECK_ID]
    assert len(matches) == 1
    return matches[0]


def _module(root: Path, text: str) -> None:
    module = root / "packages" / "pkg" / "src" / "pkg" / "module.py"
    module.parent.mkdir(parents=True)
    module.write_text(text, encoding="utf-8")


def test_clean_tree_passes(tmp_path: Path) -> None:
    _module(tmp_path, "def f(project):\n    return project\n")

    assert _record(_run(tmp_path)).result == "PASS"


def test_project_name_branch_fails_with_location_and_recovery(tmp_path: Path) -> None:
    _module(
        tmp_path, 'def f(args):\n    if args.project == "acme":\n        return 1\n'
    )

    record = _record(_run(tmp_path))

    assert record.result == "FAIL"
    assert "project_name_literal_branch" in record.detail
    assert "packages/pkg/src/pkg/module.py:2" in record.detail
    assert "Recovery:" in record.detail


def test_pending_site_warns_and_stays_visible(tmp_path: Path) -> None:
    _module(tmp_path, 'RECEIPT_PROJECT = "acme"\n')
    pending = Allowance(
        "packages/pkg/src/pkg/module.py", "RECEIPT_PROJECT", "in flight", pending=True
    )

    record = _record(_run(tmp_path, allowances=(pending,)))

    assert record.result == "WARN"
    assert "RECEIPT_PROJECT" in record.detail


def test_stale_allowance_fails(tmp_path: Path) -> None:
    _module(tmp_path, "X = 1\n")
    gone = Allowance("packages/pkg/src/pkg/module.py", "OLD", "removed")

    record = _record(_run(tmp_path, allowances=(gone,)))

    assert record.result == "FAIL"
    assert "stale allowance" in record.detail


def test_no_repo_root_is_not_applicable() -> None:
    record = _record(_run(None))

    assert record.result == "N/A"
    assert "no repo root" in record.detail


def test_live_tree_has_no_unallowed_project_name_branches() -> None:
    root = Path(__file__).resolve().parents[3]

    record = _record(_run(root, names=_LIVE_NAMES, allowances=None))

    assert record.result in {"PASS", "WARN"}, record.detail
