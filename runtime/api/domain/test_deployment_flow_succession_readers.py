"""Readers that honour a retired pin's succession chain.

Approval, run coverage, the session roster, and the delivery ladder's
containment walk each read which flows close an item. A pin whose flow was
retired closes on its same-target successor and on the retired flow itself,
and a successor that delivers somewhere else is never followed.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.api.service_client_delivery_approval import approval_flow_id
from yoke_core.domain import delivery_evidence_ladder as ladder
from yoke_core.domain.deployment_flow_succession import successor_flows
from yoke_core.domain.deployment_item_flow_resolution import (
    item_closing_flows,
    item_completion_flow,
)
from yoke_core.domain.deployment_member_coverage_batch import member_run_coverages
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    ContainmentVerdict,
)
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.session_item_delivery_status import _chosen_run

_STAGES = json.dumps([{"name": "deploy", "step_runner": "auto"}])


def _flow(conn: Any, flow_id: str, *, status: str = "active", **extra: Any) -> None:
    supersedes = extra.pop("supersedes", None)
    cmd_create(
        conn, flow_id, "yoke", flow_id, "", _STAGES,
        status=status, supersedes_flow_id=supersedes,
    )
    for column, value in extra.items():
        conn.execute(
            f"UPDATE deployment_flows SET {column} = %s WHERE id = %s",
            (value, flow_id),
        )
    conn.commit()


def _retired_pair(conn: Any, prefix: str) -> tuple[str, str]:
    old, new = f"{prefix}-old", f"{prefix}-new"
    _flow(conn, old, status="disabled")
    _flow(conn, new, supersedes=old)
    return old, new


def _pinned_item(conn: Any, item_id: int, flow_id: str) -> None:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=flow_id,
    )


def _member_run(
    conn: Any, item_id: int, run_id: str, flow: str, status: str
) -> None:
    conn.execute(
        "INSERT INTO deployment_runs("
        "id, project_id, flow, release_lineage, status, created_at, completed_at) "
        "VALUES (%s, 1, %s, %s, %s, '2026-10-01', '2026-10-01')",
        (run_id, flow, "b" * 40, status),
    )
    if item_id:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
            "VALUES (%s, %s, '2026-10-01')",
            (run_id, item_id),
        )
    conn.commit()


def test_a_successor_with_another_delivery_tier_is_not_followed(
    test_db: Any,
) -> None:
    _flow(test_db, "tier-prod-old", status="disabled")
    _flow(
        test_db, "tier-qa-only", supersedes="tier-prod-old", target_tier="ephemeral"
    )
    _pinned_item(test_db, 9391, "tier-prod-old")

    assert successor_flows(test_db, ["tier-prod-old"]) == {
        "tier-prod-old": "tier-prod-old"
    }
    # The retired pin stays the completion flow, so the existing
    # no-active-completion-flow refusal still names it.
    assert item_completion_flow(test_db, 9391) == "tier-prod-old"
    assert item_closing_flows(test_db, 9391) == {"tier-prod-old"}


def test_approval_keeps_an_active_runs_own_flow(test_db: Any) -> None:
    old, new = _retired_pair(test_db, "approve")
    started_on_old = SimpleNamespace(flow=old)
    assert approval_flow_id(test_db, old, started_on_old) == old
    assert approval_flow_id(test_db, old, None) == new
    assert approval_flow_id(test_db, "", started_on_old) == ""


def test_run_coverage_counts_a_predecessor_run_as_closing(test_db: Any) -> None:
    old, new = _retired_pair(test_db, "coverage")
    _flow(test_db, "coverage-unrelated")
    _pinned_item(test_db, 9392, old)
    _member_run(test_db, 9392, "run-coverage-old", old, "succeeded")
    _member_run(test_db, 9392, "run-coverage-other", "coverage-unrelated", "succeeded")

    assert member_run_coverages(
        test_db, run_id="run-coverage-old", item_ids=[9392]
    )[9392].closes
    assert not member_run_coverages(
        test_db, run_id="run-coverage-other", item_ids=[9392]
    )[9392].closes


def test_the_roster_release_view_takes_any_closing_flow() -> None:
    runs = [
        {"run_id": "run-other", "flow": "roster-other", "status": "succeeded"},
        {"run_id": "run-old", "flow": "roster-old", "status": "succeeded"},
    ]
    chosen = _chosen_run(runs, closing_flows=frozenset({"roster-new", "roster-old"}))
    assert chosen is not None and chosen["run_id"] == "run-old"
    assert _chosen_run(runs, closing_flows=frozenset()) is None


def test_containment_finds_a_release_on_the_retired_pin(
    test_db: Any, monkeypatch
) -> None:
    old, new = _retired_pair(test_db, "ladder")
    _pinned_item(test_db, 9393, old)
    # A release of the retired flow that never enrolled the item, and a
    # release of an unrelated flow: only the first may answer for it.
    _flow(test_db, "ladder-unrelated")
    _member_run(test_db, 0, "run-ladder-old", old, "succeeded")
    _member_run(test_db, 0, "run-ladder-other", "ladder-unrelated", "succeeded")
    asked: list[str] = []

    def _contains(_conn, _project, *, candidate_lineage, commit_sha):
        asked.append(candidate_lineage)
        return ContainmentVerdict(CONTAINED)

    # Ancestry is a git question; everything else here is the real database.
    monkeypatch.setattr(ladder, "item_merge_identity", lambda _c, _i: "a" * 40)
    monkeypatch.setattr(ladder, "candidate_contains_commit", _contains)

    verdict = ladder.delivery_evidence(test_db, 9393)
    assert verdict.discharged
    assert verdict.run_id == "run-ladder-old"
    assert verdict.source == ladder.SOURCE_CONTAINMENT
    assert len(asked) == 1

    monkeypatch.setattr(
        ladder,
        "candidate_contains_commit",
        lambda *_a, **_k: ContainmentVerdict(NOT_CONTAINED),
    )
    assert not ladder.delivery_evidence(test_db, 9393).discharged
