# ruff: noqa: F811
"""Authoring and reader surfaces for deployed dependency facts."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.test_dependency_deployed_satisfaction import (
    _insert_edge,
    _insert_item,
    dependency_conn,  # noqa: F401
)
from runtime.api.frontier_test_helpers import (
    insert_dep as insert_frontier_dep,
    insert_item as insert_frontier_item,
)
from yoke_core.domain import check_hard_blocks
from yoke_core.domain.dependency_explanation import dependency_wait_summary
from yoke_core.domain.dependency_planning import evaluate_item_gate
from yoke_core.domain.environment_delivery_record import UnregisteredEnvironment
from yoke_core.domain.frontier_compute import compute_frontier
from yoke_core.domain.item_dependency import (
    cmd_dependency_add,
    cmd_dependency_update,
)


def test_authoring_accepts_registered_and_refuses_unknown_environment(
    dependency_conn: Any,
) -> None:
    _insert_item(dependency_conn, 1)
    _insert_item(dependency_conn, 2)
    assert cmd_dependency_add(
        dependency_conn,
        "YOK-1",
        "YOK-2",
        "operator",
        satisfaction="fact:deployed:prod",
    ) == "OK"
    with pytest.raises(UnregisteredEnvironment, match="environment_unregistered"):
        cmd_dependency_update(
            dependency_conn,
            "YOK-1",
            "YOK-2",
            satisfaction="fact:deployed:preview",
        )
    stored = dependency_conn.execute(
        "SELECT satisfaction FROM item_dependencies"
    ).fetchone()[0]
    assert stored == "fact:deployed:prod"


def test_authoring_rejects_unknown_satisfaction_with_grammar(
    dependency_conn: Any,
) -> None:
    _insert_item(dependency_conn, 1)
    _insert_item(dependency_conn, 2)
    with pytest.raises(ValueError, match="unknown_satisfaction"):
        cmd_dependency_add(
            dependency_conn,
            "YOK-1",
            "YOK-2",
            "operator",
            satisfaction="fact:released",
        )


def test_gate_readers_and_explanations_name_the_environment(
    dependency_conn: Any,
) -> None:
    _insert_item(dependency_conn, 1)
    _insert_item(dependency_conn, 2, status="implemented", merged=True)
    _insert_edge(dependency_conn, 1, 2)
    result = evaluate_item_gate(dependency_conn, "YOK-1", "activation")
    assert result.is_blocked is True
    assert "merged, not yet deployed to prod" in result.unsatisfied_blockers[0].reason

    lines = check_hard_blocks.evaluate_blockers(1, conn=dependency_conn)
    assert len(lines) == 1
    assert "fact:deployed:prod" in lines[0]
    assert "merged, not yet deployed to prod" in lines[0]
    assert dependency_wait_summary("YOK-2", "fact:deployed:prod") == (
        "Waits for YOK-2 to deploy to prod"
    )


def test_frontier_reason_names_blocker_and_environment(dependency_conn: Any) -> None:
    insert_frontier_item(dependency_conn, 1, status="idea")
    insert_frontier_item(dependency_conn, 2, status="implemented")
    dependency_conn.execute(
        "UPDATE items SET merged_at=%s WHERE id=2",
        ("2026-09-03T12:00:00Z",),
    )
    insert_frontier_dep(
        dependency_conn,
        "YOK-1",
        "YOK-2",
        satisfaction="fact:deployed:prod",
    )
    result = compute_frontier(dependency_conn, [1], emit_events=False)
    dependent = next(item for item in result.blocked if item.item_id == 1)
    assert any(
        reason.startswith("Waits for YOK-2 to deploy to prod")
        for reason in dependent.blocked_reasons
    )
