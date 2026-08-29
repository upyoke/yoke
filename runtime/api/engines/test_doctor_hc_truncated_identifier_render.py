"""Tests for HC-truncated-identifier-render."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_truncated_identifier_render as hc


def _make_args() -> DoctorArgs:
    return DoctorArgs(
        file=None,
        fix=False,
        only=None,
        quick=False,
        project="yoke",
        db_path="unused",
    )


def _write(root: Path, relative: str, content: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _run_hc(root: Path) -> RecordCollector:
    rec = RecordCollector()
    with mock.patch.object(hc, "_resolve_repo_root", return_value=str(root)):
        hc.hc_truncated_identifier_render(None, _make_args(), rec)
    return rec


def _only_result(rec: RecordCollector):
    matching = [row for row in rec.results if row.check_id == hc.HC_ID]
    assert len(matching) == 1, matching
    return matching[0]


def _relatives(hits) -> list[str]:
    return [hit.relative_path for hit in hits]


def test_python_slice_of_a_session_id_is_a_hit(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/render.py",
        'def line(session_id):\n    return f"session {session_id[:8]}"\n',
    )
    assert _relatives(hc.scan(tmp_path)) == ["packages/render.py"]


def test_wrapped_python_slice_is_a_hit(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/render.py",
        'def line(row):\n    return str(row.message_id)[:12]\n',
    )
    assert _relatives(hc.scan(tmp_path)) == ["packages/render.py"]


def test_identifier_column_declaring_a_width_is_a_hit(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/table.py",
        'COLUMNS = (\n'
        '    ("TARGET", lambda row: row.get("target_session_id"), 20),\n'
        ')\n',
    )
    assert _relatives(hc.scan(tmp_path)) == ["packages/table.py"]


def test_identifier_column_without_a_width_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/table.py",
        'COLUMNS = (\n'
        '    ("TARGET", lambda row: row.get("target_session_id"), None),\n'
        ')\n',
    )
    assert hc.scan(tmp_path) == []


def test_browser_slice_of_a_session_id_is_a_hit(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/view.js",
        'function label(sessionId) {\n'
        '  return `session ${sessionId.slice(0, 8)}`;\n'
        '}\n',
    )
    assert _relatives(hc.scan(tmp_path)) == ["packages/view.js"]


def test_browser_slice_of_a_wrapped_session_id_is_a_hit(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/view.js",
        'const label = String(row.sessionId).slice(0, 8);\n',
    )
    assert _relatives(hc.scan(tmp_path)) == ["packages/view.js"]


def test_capping_a_list_of_ids_is_not_truncation(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/render.py",
        'def preview(session_ids):\n    return ", ".join(session_ids[:10])\n',
    )
    assert hc.scan(tmp_path) == []


def test_digest_fingerprints_stay_out_of_scope(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/render.py",
        'def fingerprint(head_sha):\n    return head_sha[:12]\n',
    )
    _write(
        tmp_path,
        "packages/view.js",
        'const short = String(revision.content_sha256).slice(0, 8);\n',
    )
    assert hc.scan(tmp_path) == []


def test_archive_and_generated_snapshot_are_not_scanned(tmp_path: Path) -> None:
    body = 'x = session_id[:8]\n'
    _write(tmp_path, "docs/archive/note.py", body)
    _write(
        tmp_path,
        "packages/yoke-core/src/yoke_core/install_bundle_tree/mirror.py",
        body,
    )
    assert hc.scan(tmp_path) == []


def test_test_files_may_write_the_shape_the_guard_forbids(
    tmp_path: Path,
) -> None:
    body = 'x = session_id[:8]\n'
    _write(tmp_path, "packages/test_render.py", body)
    _write(tmp_path, "packages/render_test.py", body)
    assert hc.scan(tmp_path) == []


def test_hit_fails_the_check_and_names_the_location(tmp_path: Path) -> None:
    _write(tmp_path, "packages/render.py", 'x = f"{session_id[:8]}"\n')
    with mock.patch.object(hc, "_EXEMPTIONS", ()):
        result = _only_result(_run_hc(tmp_path))
    assert result.result == "FAIL"
    assert "packages/render.py:1" in result.detail


def test_clean_tree_passes(tmp_path: Path) -> None:
    _write(tmp_path, "packages/render.py", 'x = f"{session_id}"\n')
    with mock.patch.object(hc, "_EXEMPTIONS", ()):
        result = _only_result(_run_hc(tmp_path))
    assert result.result == "PASS"


def test_exempt_path_is_not_reported_but_must_still_truncate(
    tmp_path: Path,
) -> None:
    exempt = ("packages/external.py", "external tool's own naming")
    _write(tmp_path, "packages/external.py", 'p = root / session_id[:8]\n')
    with mock.patch.object(hc, "_EXEMPTIONS", (exempt,)):
        assert hc.scan(tmp_path) == []
        assert hc.stale_exemptions(tmp_path) == []
        _write(tmp_path, "packages/external.py", 'p = root / session_id\n')
        assert hc.stale_exemptions(tmp_path) == ["packages/external.py"]


def test_this_repository_renders_no_identifier_fragment() -> None:
    from yoke_core.api.repo_root import find_repo_root

    repo_root = Path(find_repo_root())
    hits = hc.scan(repo_root)
    assert not hits, "\n".join(str(hit) for hit in hits)
    assert hc.stale_exemptions(repo_root) == []
