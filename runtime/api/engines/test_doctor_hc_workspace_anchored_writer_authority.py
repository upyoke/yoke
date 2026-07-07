"""Tests for ``HC-workspace-anchored-writer-authority``.

Verifies that:

* Every tracked-source writer in the ``IN_SCOPE_WRITERS`` list
  PASSes the HC against the live repo.
* A synthetic test-fixture writer that bypasses the helper FAILs the
  HC's bypass detector when passed through ``extra_scan_paths``.
* The doctor entry point reports PASS on the clean live tree.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.doctor_hc_workspace_anchored_writer_authority import (
    HC_NAME,
    HELPER_SYMBOL,
    IN_SCOPE_WRITERS,
    hc_workspace_anchored_writer_authority,
    scan_for_bypass,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def _project_root() -> Path:
    """Return the live Yoke checkout root the HC scans."""
    return Path(__file__).resolve().parents[3]


def test_in_scope_writers_pass_scan_on_live_tree() -> None:
    """Every writer in ``IN_SCOPE_WRITERS`` calls the helper on disk."""
    repo_root = _project_root()
    bypasses, _ = scan_for_bypass(repo_root)
    assert bypasses == [], (
        f"In-scope writers missing `{HELPER_SYMBOL}` call: {bypasses!r}"
    )


def test_in_scope_writers_list_is_non_empty() -> None:
    """Regression guard against accidentally clearing the enforcement scope."""
    assert len(IN_SCOPE_WRITERS) >= 4


def test_in_scope_writers_exist_on_live_tree() -> None:
    """Regression guard against stale paths silently shrinking scan scope."""
    repo_root = _project_root()
    missing = [p for p in IN_SCOPE_WRITERS if not (repo_root / p).is_file()]
    assert missing == []


def test_fixture_writer_bypassing_helper_is_detected(tmp_path: Path) -> None:
    """A synthetic writer module without the helper call FAILs detection.

    Lands the fixture under a temp repo_root, then exercises
    ``scan_for_bypass`` with ``extra_scan_paths``. The bypass detector
    surfaces the fixture as a bypass writer.
    """
    fake_relpath = "runtime/api/domain/fake_bypass_writer.py"
    fake_path = tmp_path / fake_relpath
    fake_path.parent.mkdir(parents=True)
    fake_path.write_text(
        "from pathlib import Path\n\n"
        "def write_thing(out: Path, content: str) -> None:\n"
        "    out.write_text(content, encoding='utf-8')\n"
    )
    in_scope, extra = scan_for_bypass(
        tmp_path,
        in_scope=(),
        extra_scan_paths=(fake_relpath,),
    )
    assert in_scope == []
    assert extra == [fake_relpath]


def test_fixture_writer_calling_helper_passes(tmp_path: Path) -> None:
    """A fixture writer that imports and calls the helper is not flagged."""
    fake_relpath = "runtime/api/domain/fake_clean_writer.py"
    fake_path = tmp_path / fake_relpath
    fake_path.parent.mkdir(parents=True)
    fake_path.write_text(
        "from pathlib import Path\n"
        "from yoke_core.domain.workspace_authority import "
        "assert_target_under_session_work_authority\n\n"
        "def write_thing(out: Path, content: str) -> None:\n"
        "    assert_target_under_session_work_authority(out)\n"
        "    out.write_text(content, encoding='utf-8')\n"
    )
    in_scope, extra = scan_for_bypass(
        tmp_path,
        in_scope=(),
        extra_scan_paths=(fake_relpath,),
    )
    assert in_scope == []
    assert extra == []


def test_doctor_entry_passes_on_clean_live_tree() -> None:
    """End-to-end: the doctor entry records PASS for the live retrofit."""
    rec = RecordCollector()
    hc_workspace_anchored_writer_authority(
        conn=None, args=DoctorArgs(project="yoke"), rec=rec,
    )
    assert rec.results, "doctor HC produced no result"
    result = rec.results[-1]
    assert result.check_id == HC_NAME
    assert result.result == "PASS", (
        f"expected PASS, got {result.result}: {result.detail}"
    )
