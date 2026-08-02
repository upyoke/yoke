"""Atomic task-scoped claim registration and reuse regressions."""

from __future__ import annotations

import pytest

from runtime.api.domain.path_claim_task_test_support import (
    seed_epic,
    seed_target,
    seed_worker_task,
)
from yoke_core.domain._path_claims_test_helpers import local_human
from yoke_core.domain.path_claim_task_coverage import evaluate_task_coverage
from yoke_core.domain.path_claim_task_registration import register_for_task


def _insert_registration_event(conn, *, item_id: int, event_id: str) -> None:
    conn.execute(
        "INSERT INTO events "
        "(event_id, source_type, session_id, severity, event_kind, "
        "event_type, event_name, project_id, item_id, created_at) "
        "VALUES (%s, 'system', 'test', 'INFO', 'lifecycle', "
        "'path_claim', 'PathClaimRegistered', "
        "(SELECT project_id FROM items WHERE id = %s), %s, "
        "'2026-07-28T00:00:00Z')",
        (event_id, item_id, str(item_id)),
    )


def test_registration_emits_only_after_binding_and_commits_together(
    test_db,
    tmp_path,
    monkeypatch,
) -> None:
    from yoke_core.domain import path_claim_task_registration
    from yoke_core.domain import path_claims_events

    item_id = seed_epic(test_db, item_id=21101)
    seed_worker_task(
        test_db,
        item_id=item_id,
        task_num=1,
        lane_path=tmp_path / "worker",
        budget_path="src/atomic.py",
    )
    seed_target(test_db, item_id=item_id, path="src/atomic.py")
    observations: list[str] = []

    def _registered(*, conn, claim, project=None):
        assert conn.execute(
            "SELECT 1 FROM path_claim_task_bindings "
            "WHERE claim_id = %s AND epic_id = %s AND task_num = 1",
            (claim["id"], item_id),
        ).fetchone()
        observations.append("registered")
        _insert_registration_event(
            conn,
            item_id=item_id,
            event_id="evt-task-registration",
        )
        return "evt-task-registration"

    def _symlinks(conn, *, claim_id, **kwargs):
        assert conn.execute(
            "SELECT 1 FROM path_claim_task_bindings WHERE claim_id = %s",
            (claim_id,),
        ).fetchone()
        observations.append("symlinks")

    monkeypatch.setattr(path_claims_events, "emit_registered", _registered)
    monkeypatch.setattr(
        path_claim_task_registration,
        "emit_decisions",
        _symlinks,
    )

    claim_id = register_for_task(
        test_db,
        item_id=item_id,
        task_num=1,
        integration_target="main",
        paths=["src/atomic.py"],
        actor_id=local_human(test_db),
    )

    assert observations == ["registered", "symlinks"]
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM path_claim_task_bindings WHERE claim_id = %s",
            (claim_id,),
        ).fetchone()[0]
        == 1
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM events WHERE event_id = 'evt-task-registration'"
        ).fetchone()[0]
        == 1
    )


def test_registration_failure_rolls_back_claim_binding_and_event(
    test_db,
    tmp_path,
    monkeypatch,
) -> None:
    from yoke_core.domain import path_claim_task_registration
    from yoke_core.domain import path_claims_events

    item_id = seed_epic(test_db, item_id=21102)
    seed_worker_task(
        test_db,
        item_id=item_id,
        task_num=1,
        lane_path=tmp_path / "worker",
        budget_path="src/rollback.py",
    )
    seed_target(test_db, item_id=item_id, path="src/rollback.py")

    def _registered(*, conn, claim, project=None):
        _insert_registration_event(
            conn,
            item_id=item_id,
            event_id="evt-task-rollback",
        )
        return "evt-task-rollback"

    def _fail_symlinks(*args, **kwargs):
        raise RuntimeError("forced post-bind failure")

    monkeypatch.setattr(path_claims_events, "emit_registered", _registered)
    monkeypatch.setattr(
        path_claim_task_registration,
        "emit_decisions",
        _fail_symlinks,
    )

    with pytest.raises(RuntimeError, match="forced post-bind failure"):
        register_for_task(
            test_db,
            item_id=item_id,
            task_num=1,
            integration_target="main",
            paths=["src/rollback.py"],
            actor_id=local_human(test_db),
        )

    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM path_claims "
            "WHERE owner_kind = 'item' AND owner_item_id = %s",
            (item_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM path_claim_task_bindings WHERE epic_id = %s",
            (item_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM events WHERE event_id = 'evt-task-rollback'"
        ).fetchone()[0]
        == 0
    )


def test_reused_claim_widens_without_losing_existing_task_binding(
    test_db,
    tmp_path,
) -> None:
    item_id = seed_epic(test_db, item_id=21103)
    for task_num, path in ((1, "src/one.py"), (2, "src/two.py")):
        seed_worker_task(
            test_db,
            item_id=item_id,
            task_num=task_num,
            lane_path=tmp_path / f"worker-{task_num}",
            budget_path=path,
        )
        seed_target(test_db, item_id=item_id, path=path)

    first = register_for_task(
        test_db,
        item_id=item_id,
        task_num=1,
        integration_target="main",
        paths=["src/one.py"],
        actor_id=local_human(test_db),
    )
    second = register_for_task(
        test_db,
        item_id=item_id,
        task_num=2,
        integration_target="main",
        paths=["src/two.py"],
        actor_id=local_human(test_db),
    )

    assert second == first
    assert {
        int(row[0])
        for row in test_db.execute(
            "SELECT task_num FROM path_claim_task_bindings WHERE claim_id = %s",
            (first,),
        ).fetchall()
    } == {1, 2}
    assert evaluate_task_coverage(test_db, item_id).verdict == "pass"
