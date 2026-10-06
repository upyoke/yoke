"""Stage handoff lint catches directives without banning internal procedure calls."""

from pathlib import Path

import pytest

from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_project_checks import check_skill_stage_handoffs as check


def _corpus(tmp_path: Path, text: str, owner: str = "idea") -> Path:
    root = tmp_path / check.SKILL_ROOT / owner
    root.mkdir(parents=True)
    (root / "notes.md").write_text(text)
    return tmp_path


@pytest.mark.parametrize(
    "text",
    [
        "Run `/yoke refine ITEM` next.",
        "Blitz uses `/yoke refine` and then `/yoke blitz`.",
        "Next step:\n/yoke polish ITEM",
        "Next: `/yoke polish ITEM`.",
        "Complete this segment before handing off to `/yoke usher ITEM`.",
        "Use\n`/yoke usher ITEM` to merge.",
        "Repair the budget through `/yoke refine ITEM` while it is in refinement.",
        "Print: `All tasks complete. Run '/yoke polish ITEM'.`",
        "Include the exact `/yoke blitz ITEM` handoff.",
        "```text\n/yoke refine ITEM\n```",
    ],
)
def test_operator_handoffs_fail(tmp_path, text):
    findings = check.scan_handoffs(_corpus(tmp_path, text))
    assert findings
    assert "next_skill_id" in findings[0]


@pytest.mark.parametrize(
    "text",
    [
        "Refinement linking belongs to `/yoke refine`.",
        "Do not start `/yoke blitz` before the link exists.",
        "Next step: /yoke {NEXT_SKILL_ID} ITEM",
        "Invoke `/yoke refine ITEM` by reading and following `refine/SKILL.md`.",
        "`/yoke refine ITEM` — critique item artifacts.",
        'Do NOT print "next step: /yoke refine" while the gate is blocked.',
        "On the next pass, `/yoke refine` will refuse the unfinished artifact.",
        "This branch does NOT:\n- Modify items\n- Invoke `/yoke refine` or `/yoke shepherd`",
        "```text\n/yoke refine ITEM Critique and improve item artifacts\n/yoke polish ITEM Review and finish implementation\n```",
        "- Dash: `/yoke dash ITEM`; one leg through merge.\n- Blitz: `/yoke blitz ITEM` after the document handoff.",
    ],
)
def test_descriptions_dynamic_handoffs_and_internal_calls_pass(tmp_path, text):
    assert not check.scan_handoffs(_corpus(tmp_path, text))


def test_same_skill_reentry_passes(tmp_path):
    assert not check.scan_handoffs(
        _corpus(tmp_path, "Run `/yoke refine ITEM` to resume.", owner="refine")
    )


def test_internal_call_needs_target_procedure(tmp_path):
    assert check.scan_handoffs(_corpus(tmp_path, "Invoke `/yoke refine ITEM`."))


def test_findings_name_wrapped_command_line(tmp_path):
    findings = check.scan_handoffs(
        _corpus(tmp_path, "# Notes\n\nUse\n`/yoke refine ITEM`.")
    )
    assert ".agents/skills/yoke/idea/notes.md:4:" in findings[0]


def test_health_check_reports_fail_and_unavailable_corpus(tmp_path, monkeypatch):
    root = _corpus(tmp_path, "Next step: /yoke refine ITEM")
    monkeypatch.setattr(check, "_resolve_repo_root", lambda: str(root))
    rec = RecordCollector()
    check.hc_skill_stage_handoffs(None, DoctorArgs(), rec)
    assert rec.results[-1].result == "FAIL"
    monkeypatch.setattr(check, "_resolve_repo_root", lambda: None)
    rec = RecordCollector()
    check.hc_skill_stage_handoffs(None, DoctorArgs(), rec)
    assert rec.results[-1].result == "N/A"


def test_refine_blitz_path_links_one_document_and_hands_off():
    root = Path(__file__).resolve().parents[3] / ".agents/skills/yoke"
    refine = (root / "refine/SKILL.md").read_text()
    protocol = (root / "refine/update-protocol.md").read_text()
    handoff = (root / "refine/blitz-execution-document.md").read_text()

    assert "ITEM_NEXT_SKILL=blitz" in refine
    assert "blitz-execution-document.md" in refine
    assert "strategy.execution.link" in protocol
    for required in (
        "Select exactly one document",
        "strategy.execution.link",
        "yoke strategy execution link",
        "strategy.execution.get",
        "yoke strategy execution get",
        "execution.execution_document.slug",
        "Next step: /yoke {NEXT_SKILL_ID}",
    ):
        assert required in handoff
