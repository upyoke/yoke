"""CLI adapter payloads for Dash and Blitz direct execution."""

from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from yoke_cli.commands import _helpers, direct_workflow_worktree
from yoke_cli.commands.adapters import blitz, dash, lane_tree
from yoke_cli.commands.adapters import (
    field_note_promote as field_note_promote_adapter,
)
from yoke_cli.commands.registry_direct_workflows import (
    DIRECT_WORKFLOW_SUBCOMMAND_ALIAS_REGISTRY,
    DIRECT_WORKFLOW_SUBCOMMAND_REGISTRY,
)
from yoke_cli.operation_inventory_direct_workflows import (
    PERMANENT_ROWS,
    WRAPPED_ROWS,
)
from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS


def _capture(monkeypatch, module):
    captured = {}

    def _dispatch(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(module, "dispatch_and_emit", _dispatch)
    return captured


def test_dash_filing_uses_cli_provenance_and_tightening_posture(monkeypatch):
    captured = _capture(monkeypatch, dash)

    assert dash.dash_file([
        "Tighten footer",
        "Fix the footer copy.",
        "--project",
        "yoke",
        "--path-claims",
        "--approval-on-done",
        "--deployment",
        "--execution-instructions-considered",
    ]) == 0

    assert captured["function_id"] == "items.create"
    assert captured["payload"] == {
        "title": "Tighten footer",
        "instruction": "Fix the footer copy.",
        "workflow": "dash",
        "entry_surface": "cli",
        "workflow_posture": {
            "path_claims": True,
            "approval_on_done": True,
            "deployment": True,
        },
        "project": "yoke",
        "execution_instructions_considered": True,
    }


def test_dash_filing_never_attests_for_the_caller(monkeypatch):
    captured = _capture(monkeypatch, dash)

    assert dash.dash_file(["Tighten footer", "Fix the footer copy."]) == 0

    # The flag records what the filer did before authoring; an adapter
    # that defaulted it to true would attest a read that never happened.
    assert captured["payload"]["execution_instructions_considered"] is False


def test_dash_filing_help_lists_priority_choices(capsys):
    with pytest.raises(SystemExit) as raised:
        dash.dash_file(["--help"])
    assert raised.value.code == 0
    help_text = capsys.readouterr().out
    assert "{high,medium,low}" in help_text
    assert "Priority bucket: high, medium, or low." in help_text


def test_dash_filing_accepts_named_priority(monkeypatch):
    captured = _capture(monkeypatch, dash)

    assert dash.dash_file([
        "Tighten footer",
        "Fix the footer copy.",
        "--priority",
        "high",
    ]) == 0
    assert captured["payload"]["priority"] == "high"


def test_dash_filing_rejects_unknown_priority(capsys):
    assert dash.dash_file([
        "Tighten footer",
        "Fix the footer copy.",
        "--priority",
        "P2",
    ]) == 2
    err = capsys.readouterr().err
    assert "invalid choice" in err
    assert "P2" in err


def test_dash_evidence_adapter_records_actual_files_and_posture(monkeypatch):
    captured = _capture(monkeypatch, dash)

    assert dash.dash_evidence([
        "YOK-9",
        "--result",
        "Updated footer",
        "--verification",
        "UI test passed",
        "--commit-sha",
        "abc1234",
        "--merge-sha",
        "def5678",
        "--path",
        "ui/footer.js",
        "--posture-check",
        "deployment=completed",
        "--tree-root",
        "/repo/.worktrees/lane",
        "--tree-head-sha",
        "abc1234",
    ]) == 0

    assert captured["function_id"] == "direct_workflow.dash.evidence"
    assert captured["payload"]["touched_files"] == ["ui/footer.js"]
    assert captured["payload"]["posture_checks"] == {
        "deployment": "completed",
    }
    assert captured["payload"]["tree_root"] == "/repo/.worktrees/lane"
    assert captured["payload"]["tree_head_sha"] == "abc1234"


def test_dash_survey_reports_client_local_headroom(monkeypatch):
    captured = _capture(monkeypatch, dash)
    monkeypatch.setattr(dash, "item_lane_tree", lambda *a, **k: lane_tree.LaneTree())
    monkeypatch.setattr(dash, "survey_path_sizes", lambda paths, **_: [{
        "path": paths[0],
        "current_line_count": 351,
        "remaining_headroom": -1,
        "at_or_over_limit": True,
        "limit": 350,
        "classification": "authored",
    }])

    assert dash.dash_survey([
        "YOK-9", "--path", "pkg/oversized.py",
    ]) == 0
    assert captured["payload"]["path_sizes"] == [{
        "path": "pkg/oversized.py",
        "current_line_count": 351,
        "remaining_headroom": -1,
        "at_or_over_limit": True,
        "limit": 350,
        "classification": "authored",
    }]
    out = io.StringIO()
    captured["human_writer"](
        SimpleNamespace(result={"touch_path_update": "replace"}),
        out,
        io.StringIO(),
    )
    assert "survey-touch-path-update|replace" in out.getvalue()


def test_dash_survey_records_explicit_no_change_without_sizing(monkeypatch):
    captured = _capture(monkeypatch, dash)
    monkeypatch.setattr(
        dash, "item_lane_tree",
        lambda *_a, **_k: pytest.fail("an empty survey has no tree to size"),
    )
    monkeypatch.setattr(
        dash, "survey_path_sizes",
        lambda *_a, **_k: pytest.fail("an empty survey has no paths to size"),
    )

    assert dash.dash_survey(["YOK-9", "--no-changes"]) == 0
    assert captured["payload"]["paths"] == []
    assert captured["payload"]["path_sizes"] == []
    assert captured["payload"]["no_changes"] is True


@pytest.mark.parametrize(("handler", "args", "function_id"), [
    (
        dash.dash_survey,
        ["9", "--path", "pkg/file.py"],
        "direct_workflow.dash.survey",
    ),
    (
        dash.dash_evidence,
        [
            "9", "--result", "Updated footer", "--verification", "passed",
            "--commit-sha", "abc1234", "--merge-sha", "def5678",
            "--no-changes", "--tree-root", "/lane", "--tree-head-sha", "abc1234",
        ],
        "direct_workflow.dash.evidence",
    ),
    (
        dash.dash_escalate,
        ["9", "--issue-title", "Broader repair", "--findings", "More work"],
        "direct_workflow.dash.escalate",
    ),
])
def test_dash_item_entries_attach_checkout_project_to_bare_refs(
    monkeypatch, handler, args, function_id,
):
    captured = _capture(monkeypatch, dash)
    monkeypatch.setattr(_helpers, "client_project_context", lambda _=None: "1")
    monkeypatch.setattr(dash, "item_lane_tree", lambda *a, **k: lane_tree.LaneTree())
    monkeypatch.setattr(dash, "survey_path_sizes", lambda *_a, **_k: [])

    assert handler(args) == 0

    assert captured["function_id"] == function_id
    assert captured["target"].item_ref == "9"
    assert captured["target"].project_id == "1"


def test_dash_evidence_adapter_refuses_an_unidentifiable_tree(monkeypatch):
    _capture(monkeypatch, dash)
    from yoke_core.domain import verification_tree_binding

    monkeypatch.setattr(dash, "item_lane_tree", lambda *a, **k: lane_tree.LaneTree())
    monkeypatch.setattr(
        verification_tree_binding,
        "resolve_tree_identity",
        lambda start=None: None,
    )

    assert dash.dash_evidence([
        "YOK-9",
        "--result",
        "Updated footer",
        "--verification",
        "UI test passed",
        "--commit-sha",
        "abc1234",
        "--merge-sha",
        "def5678",
        "--no-changes",
    ]) == 2


def test_blitz_survey_adapter_keeps_all_declared_paths(monkeypatch):
    captured = _capture(monkeypatch, blitz)

    assert blitz.blitz_survey([
        "YOK-10",
        "--path",
        "packages/core",
        "--path",
        ".agents/skills/yoke/blitz/SKILL.md",
    ]) == 0

    assert captured["function_id"] == "direct_workflow.blitz.survey"
    assert captured["payload"]["paths"] == [
        "packages/core",
        ".agents/skills/yoke/blitz/SKILL.md",
    ]


def test_field_note_promotion_adapter_targets_supporting_record(monkeypatch):
    captured = _capture(monkeypatch, field_note_promote_adapter)

    assert field_note_promote_adapter.field_note_promote([
        "22890",
        "--title",
        "Tighten footer",
        "--project",
        "yoke",
    ]) == 0

    assert captured["function_id"] == "ouroboros.field_note.promote"
    assert captured["payload"] == {
        "entry_id": 22890,
        "title": "Tighten footer",
        "project": "yoke",
    }


def test_direct_workflow_registry_and_inventory_are_complete():
    assert set(DIRECT_WORKFLOW_SUBCOMMAND_REGISTRY) == {
        ("direct-workflow", "dash", "survey"),
        ("direct-workflow", "blitz", "survey"),
        ("direct-workflow", "dash", "evidence"),
        ("direct-workflow", "dash", "escalate"),
        ("direct-workflow", "conflict-survey", "status"),
        ("ouroboros", "field-note", "promote"),
    }
    assert set(DIRECT_WORKFLOW_SUBCOMMAND_ALIAS_REGISTRY) == {("dash",)}
    assert len(WRAPPED_ROWS) == 7
    assert len(PERMANENT_ROWS) == 1


def test_worktree_prepare_delegates_to_engine_module(monkeypatch):
    captured = {}

    def _run(command, *, check):
        captured["command"] = command
        captured["check"] = check
        return type("Completed", (), {"returncode": 7})()

    monkeypatch.setattr(direct_workflow_worktree.subprocess, "run", _run)
    adapter = TOOL_SHAPED_SUBCOMMANDS[
        ("direct-workflow", "worktree", "prepare")
    ]

    assert adapter(["YOK-9", "--workflow", "dash"]) == 7
    assert captured["command"][1:] == [
        "-m",
        "yoke_core.domain.direct_workflow_worktree_preflight",
        "YOK-9",
        "--workflow",
        "dash",
    ]
    assert captured["check"] is False


def test_worktree_prepare_attaches_checkout_project_to_bare_ref(monkeypatch):
    captured = {}

    def _run(command, *, check):
        captured["command"] = command
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(direct_workflow_worktree.subprocess, "run", _run)
    monkeypatch.setattr(
        direct_workflow_worktree, "client_project_context", lambda: "1",
    )

    assert direct_workflow_worktree.direct_workflow_worktree_prepare([
        "9", "--workflow", "dash",
    ]) == 0
    assert captured["command"][-2:] == ["--project", "1"]
