"""Takeover follows a retired flow to the successor that now carries it."""

from __future__ import annotations

from runtime.api.domain import deployment_run_target_takeover_test_support as takeover
from runtime.api.domain.deployment_flow_succession_test_support import _flow
from runtime.api.domain.deployment_qa_takeover_identity_test_support import _execution
from runtime.api.domain.deployment_run_target_takeover_test_support import (
    NEW,
    OLD,
    PASSED,
    WAITING,
    _close_passed,
    _contains,
    _dated_copy,
    _members,
    _run,
    _seed_new,
    _seed_old,
    _take_over,
)
from yoke_core.domain.deployment_qa_execution_target import (
    validate_deployment_execution_target,
)
from yoke_core.domain.deployment_qa_takeover_identity import inherited_target

PREDECESSOR = f"flow-{OLD}"
SUCCESSOR = "flow-takeover-successor"


def _on_flow(conn, run_id: str, flow: str) -> None:
    conn.execute("UPDATE deployment_runs SET flow=%s WHERE id=%s", (flow, run_id))
    conn.commit()


def _seed_on_successor(conn, *_args, **_kwargs) -> None:
    """NEW runs on the published successor of OLD's retired flow."""
    _seed_new(conn, *_args, **_kwargs)
    _flow(conn, SUCCESSOR, supersedes=PREDECESSOR)
    _on_flow(conn, NEW, SUCCESSOR)


def _requirement_owners(conn, ids) -> set[str]:
    rows = conn.execute(
        "SELECT deployment_run_id FROM qa_requirements WHERE id=ANY(%s)", (list(ids),)
    ).fetchall()
    return {str(row["deployment_run_id"]) for row in rows}


def test_a_holder_on_a_retired_predecessor_flow_is_taken_over(test_db, monkeypatch):
    cases = _seed_old(test_db, run_qa=False)
    _close_passed(test_db)
    _seed_on_successor(test_db)
    _contains(monkeypatch)

    assert _take_over(test_db) == OLD

    assert _members(test_db, OLD) == {PASSED}
    assert _members(test_db, NEW) == {WAITING}
    assert _requirement_owners(test_db, [cases[WAITING]]) == {NEW}
    old, new = _run(test_db, OLD), _run(test_db, NEW)
    assert old["status"] == "succeeded" and old["superseded_by_run_id"] == NEW
    assert new["supersedes_run_id"] == OLD


def test_carried_qa_still_counts_as_inherited_after_a_cross_flow_takeover(
    test_db, monkeypatch
):
    monkeypatch.setattr(takeover, "_seed_new", _seed_on_successor)

    execution = _execution(test_db, monkeypatch)

    assert _run(test_db, NEW)["supersedes_run_id"] == OLD
    assert execution["deployment_run_id"] == NEW
    target = execution["execution_target"]
    assert target["deployment"]["run_id"] == OLD
    assert inherited_target(test_db, NEW, target)
    validate_deployment_execution_target(test_db, execution)


def test_a_predecessor_flow_still_active_is_not_followed(test_db, monkeypatch):
    _seed_old(test_db, run_qa=False)
    _seed_on_successor(test_db)
    test_db.execute(
        "UPDATE deployment_flows SET status='active' WHERE id=%s", (PREDECESSOR,)
    )
    test_db.commit()
    _contains(monkeypatch)

    assert _take_over(test_db) is None
    assert _run(test_db, OLD)["superseded_by_run_id"] is None
    assert _run(test_db, NEW)["supersedes_run_id"] is None


def test_a_retired_flow_succeeded_by_a_different_flow_is_not_taken_over(
    test_db, monkeypatch
):
    _seed_old(test_db, run_qa=False)
    _seed_on_successor(test_db)
    test_db.execute(
        "UPDATE deployment_flows SET created_at=%s WHERE id=%s",
        ("2026-11-01T00:00:00Z", SUCCESSOR),
    )
    _flow(
        test_db,
        "flow-takeover-newer-successor",
        supersedes=PREDECESSOR,
        created_at="2026-11-10T00:00:00Z",
    )
    _contains(monkeypatch)

    assert _take_over(test_db) is None
    assert _run(test_db, OLD)["superseded_by_run_id"] is None


def test_a_newer_run_on_an_unrelated_flow_does_not_hide_the_holder(
    test_db, monkeypatch
):
    _seed_old(test_db, run_qa=False)
    _close_passed(test_db)
    _seed_on_successor(test_db)
    _flow(test_db, "flow-takeover-unrelated")
    _dated_copy(
        test_db, "run-takeover-unrelated", status="failed", created_at="2099-01-01T00:00:00Z"
    )
    _on_flow(test_db, "run-takeover-unrelated", "flow-takeover-unrelated")
    _contains(monkeypatch)

    assert _take_over(test_db) == OLD
    assert _run(test_db, "run-takeover-unrelated")["superseded_by_run_id"] is None


def test_the_same_flow_takeover_is_unchanged(test_db, monkeypatch):
    _seed_old(test_db, run_qa=False)
    _close_passed(test_db)
    _seed_new(test_db)
    _contains(monkeypatch)

    assert _take_over(test_db) == OLD
    assert _run(test_db, NEW)["supersedes_run_id"] == OLD
    assert _members(test_db, NEW) == {WAITING}
