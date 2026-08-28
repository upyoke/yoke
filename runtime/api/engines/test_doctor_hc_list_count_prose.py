"""Tests for HC-list-count-prose."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from yoke_core.api.repo_root import find_repo_root
from yoke_core.domain.agents_render_conditional import RENDERED_AGENT_DIRS
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_list_count_prose as hc


def _make_args() -> DoctorArgs:
    return DoctorArgs(
        file=None,
        fix=False,
        only=None,
        quick=False,
        project="yoke",
        db_path="unused",
    )


def _write(root: Path, rel: str, content: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _run_hc(root: Path, conn=None) -> RecordCollector:
    rec = RecordCollector()
    with mock.patch.object(hc, "_resolve_repo_root", return_value=str(root)):
        hc.hc_list_count_prose(conn, _make_args(), rec)
    return rec


def _only_result(rec: RecordCollector):
    matching = [row for row in rec.results if row.check_id == hc.HC_ID]
    assert len(matching) == 1, matching
    return matching[0]


def _counted_list(noun: str, count_word: str, items: tuple[str, ...]) -> str:
    intro = "Work here follows " + count_word + " " + noun + ":"
    body = "\n".join(f"- {item}" for item in items)
    return f"{intro}\n{body}\n"


def test_matching_count_before_list_is_a_hit() -> None:
    text = _counted_list("rules", "six", ("a", "b", "c", "d", "e", "f"))
    hits = hc.scan_markdown_list_counts(text)
    assert [(hit.stated, hit.actual) for hit in hits] == [(6, 6)]


def test_mismatched_count_before_list_is_a_hit() -> None:
    text = _counted_list("rules", "six", ("a", "b"))
    hits = hc.scan_markdown_list_counts(text)
    assert [(hit.stated, hit.actual) for hit in hits] == [(6, 2)]


def test_count_free_intro_passes() -> None:
    text = "Work here follows these rules:\n- a\n- b\n"
    assert hc.scan_markdown_list_counts(text) == []


def test_timeout_and_version_numbers_do_not_count_as_list_length() -> None:
    text = "Wait 30 seconds:\n- retry\n- abort\n"
    assert hc.scan_markdown_list_counts(text) == []
    text = "Requires version 2:\n- install\n- restart\n"
    assert hc.scan_markdown_list_counts(text) == []


def test_stated_one_and_line_limits_are_not_list_counts() -> None:
    text = "Any entry for that one event is the regression:\n- fail\n"
    assert hc.scan_markdown_list_counts(text) == []
    text = "Plenty of headroom (<200 lines):\n- src/pkg/file.py\n"
    assert hc.scan_markdown_list_counts(text) == []


def test_colon_less_paragraph_is_not_an_intro() -> None:
    text = (
        "Skills apply three axes — reuse, quality, efficiency — plus a lens.\n"
        "- Reuse.\n"
        "- Quality.\n"
        "- Efficiency.\n"
        "- Stage weights.\n"
        "- Boundaries.\n"
    )
    assert hc.scan_markdown_list_counts(text) == []


def test_wrapped_list_items_count_as_one_entry_each() -> None:
    text = (
        "Two categories:\n"
        "- Route A, no run: empty flow\n"
        "  or internal\n"
        "- Route B, deployment run: grouped\n"
        "  by project\n"
    )
    hits = hc.scan_markdown_list_counts(text)
    assert [(hit.stated, hit.actual) for hit in hits] == [(2, 2)]


def test_quantity_not_adjacent_to_the_list_passes() -> None:
    text = (
        "There are six environments in the fleet.\n\n"
        "Do the following:\n"
        "- stage\n"
        "- prod\n"
    )
    assert hc.scan_markdown_list_counts(text) == []


def test_optional_adjective_before_noun_still_counts() -> None:
    text = (
        "Attest the four authored fields:\n"
        "- readers\n"
        "- invariants\n"
        "- rehearsal\n"
        "- residual\n"
    )
    hits = hc.scan_markdown_list_counts(text)
    assert [(hit.stated, hit.actual) for hit in hits] == [(4, 4)]


def test_archive_and_bundle_and_rendered_adapters_are_exempt(
    tmp_path: Path,
) -> None:
    bad = _counted_list("parts", "five", ("a", "b", "c", "d", "e"))
    _write(tmp_path, "docs/archive/old.md", bad)
    _write(
        tmp_path,
        "packages/yoke-core/src/yoke_core/install_bundle_tree/AGENTS.md",
        bad,
    )
    adapter = RENDERED_AGENT_DIRS[0].as_posix()
    _write(tmp_path, f"{adapter}/yoke-engineer.md", bad)
    assert hc.scan_teaching_surfaces(tmp_path) == []


def test_authored_teaching_file_is_reported(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "AGENTS.md",
        _counted_list("axes", "three", ("reuse", "quality", "efficiency")),
    )
    findings = hc.scan_teaching_surfaces(tmp_path)
    assert len(findings) == 1
    assert findings[0].startswith("AGENTS.md:1:")
    assert "stated 3" in findings[0]


def test_execution_instruction_row_is_reported() -> None:
    rows = [
        {
            "id": 1,
            "content": _counted_list("rules", "six", ("a", "b", "c", "d", "e")),
        }
    ]
    with mock.patch.object(hc, "_table_exists", return_value=True):
        with mock.patch.object(hc, "query_rows", return_value=rows):
            findings = hc.scan_execution_instruction_rows(object())
    assert len(findings) == 1
    assert findings[0].startswith("workflow_execution_instructions id=1:")
    assert "stated 6, list has 5" in findings[0]


def test_current_teaching_tree_has_no_list_count_hits() -> None:
    repo_root = find_repo_root(Path(__file__))
    findings = hc.scan_teaching_surfaces(repo_root)
    assert findings == [], "\n".join(findings)


def test_hc_fails_on_teaching_hit_and_passes_when_clean(tmp_path: Path) -> None:
    result = _only_result(_run_hc(tmp_path))
    assert result.result == "PASS", result.detail

    _write(tmp_path, "docs/guide.md", _counted_list("steps", "three", ("a", "b")))
    result = _only_result(_run_hc(tmp_path))
    assert result.result == "FAIL", result.detail
    assert "docs/guide.md" in result.detail
