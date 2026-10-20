"""A frozen roster keeps chains whole and retains passes reviewed after it froze."""

from __future__ import annotations

from typing import Any

from yoke_contracts.qa_case_starting_state import INHERIT
from yoke_core.domain import qa_plan_case_chain as chain
from yoke_core.domain import qa_plan_run_target_partition as partition

OPENER, FIRST, SECOND, NEXT_OPENER = 53800, 53801, 53802, 53900


def _case(requirement_id: int, ordinal: int, *, inherit: bool) -> dict[str, Any]:
    return {
        "requirement_id": requirement_id,
        "ordinal": ordinal,
        "case_key": f"case-{requirement_id}",
        "plan_id": 7,
        "case_position": ordinal + 1,
        "baseline_position": 0 if requirement_id < NEXT_OPENER else 1,
        "host_baseline": "clean",
        "starting_state": INHERIT if inherit else "clean",
        "runner_id": "host_control",
        "execution_target_digest": "a" * 64,
    }


def _roster() -> list[dict[str, Any]]:
    return [
        _case(OPENER, 0, inherit=False),
        _case(FIRST, 1, inherit=True),
        _case(SECOND, 2, inherit=True),
        _case(NEXT_OPENER, 3, inherit=False),
    ]


def _ids(rows: list[dict[str, Any]]) -> list[int]:
    return [int(row["requirement_id"]) for row in rows]


def _partition(monkeypatch, passed: set[int]) -> list[dict[str, Any]]:
    monkeypatch.setattr(
        partition, "target_passed_requirements", lambda *_a, **_k: set(passed)
    )
    monkeypatch.setattr(partition, "live_plan_execution_id", lambda *_a, **_k: None)
    return partition.run_target_partition(
        None,
        _roster(),
        deployment_run_id="run-20261020-003",
        deployment_stage="item-qa",
        deployment_member_item_id=3974,
    )


def test_a_chain_still_owing_a_follower_stays_whole(monkeypatch) -> None:
    kept = _partition(monkeypatch, {OPENER, FIRST, NEXT_OPENER})

    assert _ids(kept) == [OPENER, FIRST, SECOND]
    assert [row["ordinal"] for row in kept] == [0, 1, 2]


def test_a_chain_leaves_once_its_last_review_lands(monkeypatch) -> None:
    assert _ids(_partition(monkeypatch, {OPENER, FIRST, SECOND})) == [NEXT_OPENER]


def test_only_passes_after_the_last_owed_case_settle() -> None:
    roster = _roster()

    assert chain.settled_chain_tails(roster, {OPENER, SECOND}) == {SECOND}
    assert chain.settled_chain_tails(roster, {FIRST, NEXT_OPENER}) == {NEXT_OPENER}


def _begin(monkeypatch, passed: set[int], ordinal: int):
    from yoke_core.domain import qa_latest_execution, qa_plan_execution_state

    advanced: list[dict[str, Any]] = []
    monkeypatch.setattr(
        partition, "target_passed_requirements", lambda _c, rows, **_k: set(passed)
    )
    monkeypatch.setattr(
        qa_latest_execution,
        "latest_verdict_executions",
        lambda _c, ids: {int(i): {"id": 54432} for i in ids},
    )
    monkeypatch.setattr(
        qa_plan_execution_state,
        "advance_plan_execution",
        lambda _c, _e, **kwargs: advanced.append(kwargs),
    )
    monkeypatch.setattr(chain, "inherit_blocker", lambda *_a, **_k: None)
    execution = {"id": "2461dd92", "roster": _roster(), "deployment_stage": "qa"}
    settled = chain.settle_without_machine(
        None, execution, execution["roster"][ordinal], ordinal=ordinal
    )
    return settled, advanced


def test_a_follower_reviewed_after_the_roster_froze_is_retained(monkeypatch) -> None:
    settled, advanced = _begin(monkeypatch, {FIRST, SECOND}, ordinal=1)

    assert settled is not None
    state, result = settled
    assert state == "retained"
    assert result["verdict"] == "pass"
    assert result["case_outcome"] == "passed"
    assert result["retained_pass_run_id"] == 54432
    assert [entry["requirement_id"] for entry in advanced] == [FIRST]


def test_a_passed_case_still_needed_by_its_chain_runs(monkeypatch) -> None:
    settled, advanced = _begin(monkeypatch, {OPENER, FIRST}, ordinal=0)

    assert settled is None
    assert advanced == []
