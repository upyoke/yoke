"""Tests for qa_gate_summary — typed read-only QA summary.

Covers AC-1 / AC-2 / AC-3 / AC-13 / AC-14
- Target-aware unsatisfied counts.
- Browser-substrate evidence rule for ``browser_smoke`` / ``browser_diff``
  matches the verification gate.
- Per-requirement evidence (id, kind, blocking, satisfied, latest run)
  is surfaced.
- The summary is read-only — no qa_runs / qa_requirements mutations
  occur during a render.

Schema, fixture, and helpers live in
:mod:`yoke_core.domain.qa_gate_summary_test_fixtures` so this file
stays under the 350-line authored-file cap.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.qa_gate_definitions import GateTarget
from yoke_core.domain.qa_gate_summary import (
    VALID_TARGETS,
    cmd_gate_summary,
    render_gate_summary,
)
from yoke_core.domain.qa_gate_summary_test_fixtures import (  # noqa: F401
    add_artifact,
    add_requirement,
    add_run,
    qa_db,
    qa_db_no_tables,
    row_count,
)


# ---------------------------------------------------------------------------
# Targeting & validation
# ---------------------------------------------------------------------------


def test_invalid_target_raises_value_error(qa_db):
    """AC-14: only the two named targets are accepted."""
    with pytest.raises(ValueError):
        render_gate_summary(GateTarget(item_id=42), qa_db, transition_name="done")


def test_valid_targets_are_exactly_two():
    assert VALID_TARGETS == ("reviewed-implementation", "implemented")


def test_no_qa_tables_present_returns_satisfied(qa_db_no_tables):
    """Pre-migration DBs without qa_requirements should not crash."""
    summary = render_gate_summary(
        GateTarget(item_id=42), qa_db_no_tables, transition_name="reviewed-implementation"
    )
    assert summary["qa_tables_present"] is False
    assert summary["satisfied"] is True
    assert summary["requirements"] == []


def test_no_requirements_for_scope(qa_db):
    """AC-1: empty scope is satisfied, with no_requirements flag set."""
    summary = render_gate_summary(
        GateTarget(item_id=999), qa_db, transition_name="reviewed-implementation"
    )
    assert summary["qa_tables_present"] is True
    assert summary["no_requirements"] is True
    assert summary["satisfied"] is True
    assert summary["blocking_unsatisfied_count"] == 0


# ---------------------------------------------------------------------------
# Per-requirement satisfaction
# ---------------------------------------------------------------------------


def test_blocking_browser_without_substrate_run_unsatisfied(qa_db):
    """AC-2: browser_smoke requires substrate-executed pass + artifacts."""
    add_requirement(qa_db, qa_kind="browser_smoke")
    summary = render_gate_summary(
        GateTarget(item_id=42), qa_db, transition_name="reviewed-implementation"
    )
    assert summary["satisfied"] is False
    assert summary["blocking_unsatisfied_count"] == 1
    assert summary["browser_unsatisfied_count"] == 1
    [req] = summary["requirements"]
    assert req["qa_kind"] == "browser_smoke"
    assert req["satisfied"] is False


def test_browser_with_substrate_run_and_artifact_satisfied(qa_db):
    """AC-2: pass + non-agent executor + artifact satisfies the gate."""
    rid = add_requirement(qa_db, qa_kind="browser_diff")
    run_id = add_run(qa_db, rid, executor_type="browser_substrate", qa_kind="browser_diff")
    add_artifact(qa_db, run_id)
    summary = render_gate_summary(
        GateTarget(item_id=42), qa_db, transition_name="reviewed-implementation"
    )
    assert summary["satisfied"] is True
    assert summary["browser_unsatisfied_count"] == 0
    [req] = summary["requirements"]
    assert req["satisfied"] is True
    latest = req["latest_run"]
    assert latest is not None
    assert latest["verdict"] == "pass"
    assert latest["executor_type"] == "browser_substrate"
    assert latest["id"] == run_id


def test_browser_with_agent_only_run_unsatisfied(qa_db):
    """AC-2: agent-executed pass alone does NOT satisfy a browser kind."""
    rid = add_requirement(qa_db, qa_kind="browser_smoke")
    add_run(qa_db, rid, executor_type="agent", qa_kind="browser_smoke")
    summary = render_gate_summary(
        GateTarget(item_id=42), qa_db, transition_name="reviewed-implementation"
    )
    assert summary["satisfied"] is False
    [req] = summary["requirements"]
    assert req["satisfied"] is False


def test_browser_substrate_run_without_artifact_unsatisfied(qa_db):
    """AC-2: browser pass without an artifact does not satisfy."""
    rid = add_requirement(qa_db, qa_kind="browser_smoke")
    add_run(qa_db, rid, executor_type="browser_substrate", qa_kind="browser_smoke")
    summary = render_gate_summary(
        GateTarget(item_id=42), qa_db, transition_name="reviewed-implementation"
    )
    assert summary["satisfied"] is False
    [req] = summary["requirements"]
    assert req["satisfied"] is False


def test_e2e_with_passing_run_satisfied(qa_db):
    """AC-2: e2e satisfies on any passing run (no substrate-only rule)."""
    rid = add_requirement(qa_db, qa_kind="e2e")
    add_run(qa_db, rid, executor_type="ci", qa_kind="e2e")
    summary = render_gate_summary(
        GateTarget(item_id=42), qa_db, transition_name="reviewed-implementation"
    )
    assert summary["satisfied"] is True
    assert summary["e2e_unsatisfied_count"] == 0


def test_e2e_without_passing_run_unsatisfied(qa_db):
    """AC-2 / AC-3: unsatisfied e2e shows up in counts and per-row flag."""
    rid = add_requirement(qa_db, qa_kind="e2e")
    add_run(qa_db, rid, executor_type="ci", qa_kind="e2e", verdict="fail")
    summary = render_gate_summary(
        GateTarget(item_id=42), qa_db, transition_name="reviewed-implementation"
    )
    assert summary["satisfied"] is False
    assert summary["e2e_unsatisfied_count"] == 1
    [req] = summary["requirements"]
    assert req["qa_kind"] == "e2e"
    assert req["satisfied"] is False


def test_waived_requirement_treated_as_satisfied(qa_db):
    add_requirement(qa_db, qa_kind="browser_smoke", waived_at="2026-05-07T02:00:00Z")
    summary = render_gate_summary(
        GateTarget(item_id=42), qa_db, transition_name="reviewed-implementation"
    )
    assert summary["satisfied"] is True
    [req] = summary["requirements"]
    assert req["satisfied"] is True
    assert req["waived_at"] == "2026-05-07T02:00:00Z"


def test_non_blocking_unsat_does_not_count_in_blocking_total(qa_db):
    add_requirement(qa_db, qa_kind="ac_verification", blocking_mode="non_blocking")
    summary = render_gate_summary(
        GateTarget(item_id=42), qa_db, transition_name="reviewed-implementation"
    )
    assert summary["satisfied"] is True
    assert summary["blocking_unsatisfied_count"] == 0
    [req] = summary["requirements"]
    assert req["satisfied"] is False  # evidence absent — but non-blocking
    assert req["blocking_mode"] == "non_blocking"


# ---------------------------------------------------------------------------
# Phase scoping
# ---------------------------------------------------------------------------


def test_target_reviewed_implementation_filters_to_verification_phase(qa_db):
    add_requirement(qa_db, qa_kind="ac_verification", qa_phase="verification")
    add_requirement(qa_db, qa_kind="ac_verification", qa_phase="post_deploy")
    summary = render_gate_summary(
        GateTarget(item_id=42), qa_db, transition_name="reviewed-implementation"
    )
    phases = {r["qa_phase"] for r in summary["requirements"]}
    assert phases == {"verification"}


def test_target_implemented_includes_all_blocking_phases(qa_db):
    add_requirement(qa_db, qa_kind="ac_verification", qa_phase="verification")
    add_requirement(qa_db, qa_kind="ac_verification", qa_phase="post_deploy")
    summary = render_gate_summary(
        GateTarget(item_id=42), qa_db, transition_name="implemented"
    )
    phases = {r["qa_phase"] for r in summary["requirements"]}
    assert phases == {"verification", "post_deploy"}
    assert summary["blocking_unsatisfied_count"] == 2


# ---------------------------------------------------------------------------
# Read-only invariant and epic-task targeting
# ---------------------------------------------------------------------------


def test_summary_render_does_not_mutate_qa_tables(qa_db):
    rid = add_requirement(qa_db, qa_kind="ac_verification")
    add_run(qa_db, rid, executor_type="agent", qa_kind="ac_verification")
    pre_req = row_count(qa_db, "qa_requirements")
    pre_run = row_count(qa_db, "qa_runs")
    pre_art = row_count(qa_db, "qa_artifacts")
    render_gate_summary(
        GateTarget(item_id=42), qa_db, transition_name="reviewed-implementation"
    )
    assert row_count(qa_db, "qa_requirements") == pre_req
    assert row_count(qa_db, "qa_runs") == pre_run
    assert row_count(qa_db, "qa_artifacts") == pre_art


def test_epic_task_target(qa_db):
    rid = add_requirement(
        qa_db, item_id=None, epic_id=833, task_num=5, qa_kind="ac_verification",
    )
    add_run(qa_db, rid, executor_type="agent", qa_kind="ac_verification")
    summary = render_gate_summary(
        GateTarget(epic_id=833, task_num=5), qa_db,
        transition_name="reviewed-implementation",
    )
    assert summary["target"] == "epic 833/task 5"
    assert summary["satisfied"] is True


# ---------------------------------------------------------------------------
# CLI handler (cmd_gate_summary)
# ---------------------------------------------------------------------------


def test_cli_target_validation(qa_db, capsys):
    rc = cmd_gate_summary(
        db_path=qa_db, item_id=42, epic_id=None, task_num=None,
        target="invalid", as_json=False,
    )
    assert rc == 2
    assert "must be one of" in capsys.readouterr().err


def test_cli_target_requires_item_or_epic(qa_db, capsys):
    rc = cmd_gate_summary(
        db_path=qa_db, item_id=None, epic_id=None, task_num=None,
        target="reviewed-implementation", as_json=False,
    )
    assert rc == 2
    assert "item-id" in capsys.readouterr().err


def test_cli_item_and_epic_are_mutually_exclusive(qa_db, capsys):
    rc = cmd_gate_summary(
        db_path=qa_db, item_id=42, epic_id=833, task_num=5,
        target="reviewed-implementation", as_json=False,
    )
    assert rc == 2
    assert "mutually exclusive" in capsys.readouterr().err


def test_cli_json_output_is_valid_json(qa_db, capsys):
    add_requirement(qa_db, qa_kind="e2e")
    rc = cmd_gate_summary(
        db_path=qa_db, item_id=42, epic_id=None, task_num=None,
        target="reviewed-implementation", as_json=True,
    )
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["target"] == "YOK-42"
    assert parsed["transition"] == "reviewed-implementation"
    assert parsed["e2e_unsatisfied_count"] == 1


def test_cli_text_output_includes_status_and_counts(qa_db, capsys):
    add_requirement(qa_db, qa_kind="ac_verification")
    rc = cmd_gate_summary(
        db_path=qa_db, item_id=42, epic_id=None, task_num=None,
        target="reviewed-implementation", as_json=False,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Status: UNSATISFIED" in out
    assert "Blocking unsatisfied: 1" in out
    assert "ac_verification" in out


def test_cli_returns_zero_when_satisfied(qa_db, capsys):
    """AC-13: a satisfied summary still exits 0; verdict belongs to the gate."""
    rc = cmd_gate_summary(
        db_path=qa_db, item_id=999, epic_id=None, task_num=None,
        target="reviewed-implementation", as_json=False,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "No QA requirements" in out
