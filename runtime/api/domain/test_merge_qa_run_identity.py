"""Merge proof hydration follows selected identity across reordered run history."""

from itertools import permutations
from types import SimpleNamespace

import pytest

from yoke_core.domain import standalone_item_merge_qa as merge_qa
from runtime.api.domain.test_standalone_item_merge_qa import (
    MERGING_SHA,
    _item,
    _requirement,
)


def _run(run_id, verdict, outcome, *, completed=True):
    return {
        "id": run_id,
        "verdict": verdict,
        "execution_status": "captured" if completed else "running",
        "case_outcome": outcome,
        "completed_at": "2026-01-01T00:00:00Z" if completed else None,
        "raw_result": '{"verification_tree":{"head_sha":"' + MERGING_SHA + '"}}',
    }


def _history(monkeypatch, rows):
    monkeypatch.setattr(
        merge_qa,
        "call_dispatcher",
        lambda **kwargs: SimpleNamespace(success=True, result={"rows": rows}),
    )


@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_newest_passing_attempt_grades_the_same_in_every_history_order(
    tmp_path, monkeypatch, order
):
    rows = [
        _run(81, None, "needs_review"),
        _run(85, "fail", "failed"),
        _run(88, "pass", "passed"),
    ]
    requirement = _requirement(verdict="pass", sha="")
    _history(monkeypatch, [rows[i] for i in order])
    sha, error = merge_qa.preflight(
        _item(requirement), public_ref="YOK-10", repo_root=tmp_path, branch="YOK-10"
    )
    assert (sha, error) == (MERGING_SHA, "")
    assert requirement["run_id"] == 88
    assert requirement["case_outcome"] == "passed"


@pytest.mark.parametrize(
    "verdict,outcome,completed",
    [
        ("fail", "failed", True),
        (None, "running", False),
    ],
)
def test_current_failed_or_pending_attempt_cannot_borrow_an_old_pass(
    tmp_path, monkeypatch, verdict, outcome, completed
):
    requirement = _requirement(verdict=verdict, sha="", completed=completed)
    _history(
        monkeypatch,
        [
            _run(88, verdict, outcome, completed=completed),
            _run(90, "pass", "passed"),
        ],
    )
    _, error = merge_qa.preflight(
        _item(requirement), public_ref="YOK-10", repo_root=tmp_path, branch="YOK-10"
    )
    assert error
    assert requirement["run_id"] == 88
    assert requirement["case_outcome"] == outcome


@pytest.mark.parametrize("rows", [[], [_run(89, "pass", "passed")]])
def test_missing_selected_run_names_identity_failure_and_recovery(monkeypatch, rows):
    requirement = _requirement(verdict="pass", sha="")
    _history(monkeypatch, rows)
    error = merge_qa._hydrate_run_identity(requirement)
    assert "qa_run_identity_unavailable" in error
    assert "run 88" in error
    assert "refresh item detail and retry merge" in error
