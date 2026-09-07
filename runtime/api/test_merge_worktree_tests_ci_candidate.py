"""The merge boundary proves the candidate the item's own QA case declared.

The post-rebase run has to answer the same two questions the gate did —
which commit, and which producer candidate — so it reads the candidate
back from the item's QA requirement rather than from anything the merge
command was told, and it refuses a run whose candidate cannot be shown.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.merge_worktree_tests_ci_helpers import (
    bind_candidate_tree,
    existing_run,
    never,
    record_ci_runs,
    run_verification,
    stub_lane,
)

from yoke_core.domain import qa_case_ci_covering_run as covering_run
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


def test_the_merge_run_carries_the_candidate_the_items_case_declared(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """The post-rebase run proves the same candidate the QA gate proved."""
    head = "b" * 40
    candidate = {"product_ref": "c" * 40}
    seen: dict = {}
    bind_candidate_tree(monkeypatch, tmp_path, head)
    stub_lane(
        monkeypatch,
        dispatch=lambda **kwargs: seen.update(kwargs) or "55",
        await_result=lambda **kwargs: (0, "success"),
        candidate=candidate,
    )
    recorded = record_ci_runs(monkeypatch)

    assert run_verification(tmp_path) is None
    assert seen["inputs"] == candidate
    raw = json.loads(recorded[0]["raw_result"])
    assert raw["ci_workflow_inputs"] == candidate


def test_a_run_that_cannot_be_shown_to_carry_the_candidate_is_not_adopted(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    """Same commit, unknown inputs — not covering evidence."""
    head = "b" * 40
    candidate = {"product_ref": "c" * 40}
    seen: dict = {}
    bind_candidate_tree(monkeypatch, tmp_path, head)
    stub_lane(
        monkeypatch,
        dispatch=lambda **kwargs: seen.update(kwargs) or "55",
        await_result=lambda **kwargs: (0, "success"),
        covering=existing_run(head),
        candidate=candidate,
    )
    recorded = record_ci_runs(monkeypatch)

    assert run_verification(tmp_path) is None
    assert seen["inputs"] == candidate
    raw = json.loads(recorded[0]["raw_result"])
    assert raw["ci_run_source"] == covering_run.DISPATCHED
    assert raw["ci_run_id"] == "55"


def test_an_unresolvable_candidate_blocks_before_anything_is_published(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    head = "b" * 40
    bind_candidate_tree(monkeypatch, tmp_path, head)
    stub_lane(
        monkeypatch,
        dispatch=never("dispatched despite an unresolved candidate"),
        await_result=never("awaited despite an unresolved candidate"),
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_lane.push_lane",
        never("pushed despite an unresolved candidate"),
    )

    def _refuse(**_kwargs):
        raise QaCaseExecutionError("QA requirements unreadable")

    monkeypatch.setattr(
        "yoke_core.domain.qa_case_ci_candidate_inputs.item_inputs", _refuse,
    )

    assert run_verification(tmp_path) == (1, "ci candidate inputs unresolved")
