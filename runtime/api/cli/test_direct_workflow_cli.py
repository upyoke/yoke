"""CLI adapter payloads for Dash and Blitz direct execution."""

from __future__ import annotations

from yoke_cli.commands import direct_workflow_worktree
from yoke_cli.commands.adapters import blitz, dash
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
    }


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
    monkeypatch.setattr(dash, "survey_path_sizes", lambda paths: [{
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


def test_dash_evidence_adapter_resolves_the_verification_tree(monkeypatch):
    # Without overrides the adapter names the tree it is standing in, so
    # the recorded evidence always identifies what was verified.
    captured = _capture(monkeypatch, dash)
    from yoke_core.domain import verification_tree_binding

    monkeypatch.setattr(
        verification_tree_binding,
        "resolve_tree_identity",
        lambda start=None: verification_tree_binding.TreeIdentity(
            root="/resolved/lane", head_sha="feed1234",
        ),
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
    ]) == 0

    assert captured["payload"]["tree_root"] == "/resolved/lane"
    assert captured["payload"]["tree_head_sha"] == "feed1234"


def test_dash_evidence_adapter_refuses_an_unidentifiable_tree(monkeypatch):
    _capture(monkeypatch, dash)
    from yoke_core.domain import verification_tree_binding

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
    captured = _capture(monkeypatch, dash)

    assert dash.field_note_promote([
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
