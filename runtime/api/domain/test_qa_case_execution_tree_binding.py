"""Tree binding for the ``worktree_run`` QA runner.

The case runner resolves its own checkout — a case whose lane branch has
no live worktree falls back to the project checkout, which can be the
main tree while the session's claimed lane sits untouched. Since this run
IS the recorded gate, the refusal has to land before the command, and the
run record has to name the tree that produced the verdict.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import qa_case_execution, qa_case_worktree_run
from yoke_core.domain import verification_tree_binding
from yoke_core.domain.verification_tree_binding import (
    TreeBindingVerdict,
    TreeIdentity,
)

REFUSAL = "REFUSAL: cd to the claimed worktree"


def _case() -> dict:
    return {
        "requirement_id": 41,
        "item_id": 9,
        "plan_id": 5,
        "case_key": "registered",
        "method_id": "command",
        "runner_id": "worktree_run",
        "method_config": {"command": "printf 'ran'"},
        "project_id": 1,
        "project": "yoke",
        "lane_branch": None,
    }


def test_binding_refusal_stops_the_run_before_the_command(
    tmp_path: Path,
) -> None:
    dispatched: list[str] = []

    with (
        mock.patch.object(
            qa_case_execution, "_execution_checkout", return_value=tmp_path,
        ),
        mock.patch.object(
            qa_case_worktree_run.verification_tree_binding,
            "evaluate_run",
            return_value=TreeBindingVerdict(refusal=REFUSAL),
        ),
        mock.patch.object(
            qa_case_execution,
            "_dispatch",
            side_effect=lambda fid, *a, **k: dispatched.append(fid) or {},
        ),
    ):
        with pytest.raises(qa_case_execution.QaCaseExecutionError) as raised:
            qa_case_execution.execute_case_context(_case())

    assert REFUSAL in str(raised.value)
    # No run row, no artifact, no verdict — a refused run leaves no
    # record that could later read as a green.
    assert dispatched == []


def test_run_record_names_the_tree_that_produced_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    calls: list[tuple[str, dict]] = []

    def dispatch(function_id, requirement_id, payload, *, actor=None):
        calls.append((function_id, payload))
        if function_id == "qa.artifact.add":
            return {"qa_artifact_id": 88}
        return {"qa_run_id": 77}

    identity = TreeIdentity(root=str(tmp_path), head_sha="a" * 40)

    with (
        mock.patch.object(
            qa_case_execution, "_execution_checkout", return_value=tmp_path,
        ),
        mock.patch.object(
            qa_case_worktree_run.verification_tree_binding,
            "resolve_tree_identity",
            return_value=identity,
        ),
        mock.patch.object(
            qa_case_execution, "_dispatch", side_effect=dispatch,
        ),
    ):
        result = qa_case_execution.execute_case_context(_case())

    assert result["verdict"] == "pass"
    assert result["verification_tree"] == identity.as_payload()
    recorded = json.loads(dict(calls)["qa.run.add"]["raw_result"])
    assert recorded["verification_tree"] == identity.as_payload()
    completed = json.loads(dict(calls)["qa.run.complete"]["raw_result"])
    assert completed["verification_tree"] == identity.as_payload()


def test_unidentifiable_tree_records_null_rather_than_guessing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    calls: list[tuple[str, dict]] = []

    def dispatch(function_id, requirement_id, payload, *, actor=None):
        calls.append((function_id, payload))
        if function_id == "qa.artifact.add":
            return {"qa_artifact_id": 88}
        return {"qa_run_id": 77}

    with (
        mock.patch.object(
            qa_case_execution, "_execution_checkout", return_value=tmp_path,
        ),
        mock.patch.object(
            qa_case_worktree_run.verification_tree_binding,
            "resolve_tree_identity",
            return_value=None,
        ),
        mock.patch.object(
            qa_case_execution, "_dispatch", side_effect=dispatch,
        ),
    ):
        result = qa_case_execution.execute_case_context(_case())

    assert result["verification_tree"] is None
    recorded = json.loads(dict(calls)["qa.run.add"]["raw_result"])
    assert recorded["verification_tree"] is None


def test_checkout_under_the_claimed_lane_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The pass-through case the refusal must never swallow: the case
    # runs in exactly the worktree the session claimed.
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    lane = tmp_path / ".worktrees" / "lane"
    lane.mkdir(parents=True)
    monkeypatch.setattr(
        verification_tree_binding, "ambient_session_id", lambda: "sess-1",
    )
    monkeypatch.setattr(
        verification_tree_binding,
        "resolve_claim_worktrees",
        lambda _sid: [str(lane)],
    )

    with (
        mock.patch.object(
            qa_case_execution, "_execution_checkout", return_value=lane,
        ),
        mock.patch.object(
            qa_case_execution,
            "_dispatch",
            side_effect=lambda fid, rid, payload, *, actor=None: (
                {"qa_artifact_id": 88}
                if fid == "qa.artifact.add"
                else {"qa_run_id": 77}
            ),
        ),
    ):
        result = qa_case_execution.execute_case_context(_case())

    assert result["verdict"] == "pass"
