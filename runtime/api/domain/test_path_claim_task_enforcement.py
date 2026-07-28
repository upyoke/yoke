"""Task-binding, coverage, registration, and lifecycle regressions."""

from __future__ import annotations

import pytest
from psycopg.pq import TransactionStatus

from runtime.api.domain.path_claim_task_test_support import (
    bind_claim,
    seed_epic,
    seed_item_claim,
    seed_target,
    seed_worker_task,
)
from yoke_core.domain._path_claims_test_helpers import local_human
from yoke_core.domain.advance_path_claim_task_activation import (
    task_activation_block_reason,
)
from yoke_core.domain.epic_amend import task_remove
from yoke_core.domain.path_claim_required_gate import evaluate as required_gate
from yoke_core.domain.path_claim_task_bindings import (
    PathClaimTaskBindingError,
)
from yoke_core.domain.path_claim_task_coverage import (
    evaluate_task_coverage,
    path_root_covers,
)
from yoke_core.domain.path_claim_task_registration import register_for_task


def test_unbound_parent_claim_does_not_satisfy_task_coverage(
    test_db,
    tmp_path,
) -> None:
    item_id = seed_epic(test_db, item_id=21001)
    seed_worker_task(
        test_db,
        item_id=item_id,
        task_num=1,
        lane_path=tmp_path / "worker",
        budget_path="src/owned.py",
    )
    target_id = seed_target(
        test_db,
        item_id=item_id,
        path="src/owned.py",
    )
    seed_item_claim(test_db, item_id=item_id, target_ids=(target_id,))

    result = evaluate_task_coverage(test_db, item_id)

    assert result.verdict == "block"
    assert result.missing_tasks == (1,)


def test_done_task_stays_eligible_while_failed_and_stopped_tasks_do_not(
    test_db,
    tmp_path,
) -> None:
    item_id = seed_epic(test_db, item_id=21002)
    seed_worker_task(
        test_db,
        item_id=item_id,
        task_num=1,
        lane_path=tmp_path / "done",
        task_status="done",
        budget_path="src/done.py",
    )
    seed_worker_task(
        test_db,
        item_id=item_id,
        task_num=2,
        lane_path=tmp_path / "stopped",
        task_status="stopped",
    )
    seed_worker_task(
        test_db,
        item_id=item_id,
        task_num=3,
        lane_path=tmp_path / "failed",
        task_status="failed",
    )
    target_id = seed_target(
        test_db,
        item_id=item_id,
        path="src/done.py",
    )
    claim_id = seed_item_claim(
        test_db,
        item_id=item_id,
        target_ids=(target_id,),
    )

    assert evaluate_task_coverage(test_db, item_id).missing_tasks == (1,)
    bind_claim(
        test_db,
        claim_id=claim_id,
        item_id=item_id,
        task_num=1,
    )
    assert evaluate_task_coverage(test_db, item_id).verdict == "pass"


def test_file_targets_are_exact_and_directory_targets_cover_descendants() -> None:
    assert path_root_covers("src/a.py", "src/a.py", kind="file")
    assert not path_root_covers("src/a.py", "src/a.py/child", kind="file")
    assert path_root_covers("src", "src/a.py", kind="directory")
    assert not path_root_covers("src", "src2/a.py", kind="directory")


def test_empty_task_exception_requires_reason_and_reuse_closes_transaction(
    test_db,
    tmp_path,
) -> None:
    item_id = seed_epic(test_db, item_id=21003)
    seed_worker_task(
        test_db,
        item_id=item_id,
        task_num=1,
        lane_path=tmp_path / "empty",
    )

    with pytest.raises(Exception, match="reason"):
        register_for_task(
            test_db,
            item_id=item_id,
            task_num=1,
            integration_target="main",
            paths=[],
            actor_id=local_human(test_db),
            mode="exception",
        )

    claim_id = register_for_task(
        test_db,
        item_id=item_id,
        task_num=1,
        integration_target="main",
        paths=[],
        actor_id=local_human(test_db),
        mode="exception",
        exception_reason="This generated task changes no repository files.",
    )
    assert evaluate_task_coverage(test_db, item_id).verdict == "pass"
    assert (
        register_for_task(
            test_db,
            item_id=item_id,
            task_num=1,
            integration_target="main",
            paths=[],
            actor_id=local_human(test_db),
            mode="exception",
            exception_reason="This generated task changes no repository files.",
        )
        == claim_id
    )
    assert test_db.info.transaction_status is TransactionStatus.IDLE


def test_nonempty_task_cannot_register_no_path_exception(
    test_db,
    tmp_path,
) -> None:
    item_id = seed_epic(test_db, item_id=21004)
    seed_worker_task(
        test_db,
        item_id=item_id,
        task_num=1,
        lane_path=tmp_path / "worker",
        budget_path="src/change.py",
    )

    with pytest.raises(PathClaimTaskBindingError, match="persisted file budget"):
        register_for_task(
            test_db,
            item_id=item_id,
            task_num=1,
            integration_target="main",
            paths=[],
            actor_id=local_human(test_db),
            mode="exception",
            exception_reason="Incorrect exception",
        )


def test_task_removal_reconciles_binding_without_deleting_item_claim(
    test_db,
    tmp_path,
) -> None:
    item_id = seed_epic(test_db, item_id=21008)
    seed_worker_task(
        test_db,
        item_id=item_id,
        task_num=1,
        lane_path=tmp_path / "worker",
        budget_path="src/remove.py",
    )
    target_id = seed_target(
        test_db,
        item_id=item_id,
        path="src/remove.py",
    )
    claim_id = seed_item_claim(
        test_db,
        item_id=item_id,
        target_ids=(target_id,),
        state="planned",
    )
    bind_claim(
        test_db,
        claim_id=claim_id,
        item_id=item_id,
        task_num=1,
    )

    task_remove(test_db, item_id, 1)

    assert test_db.execute(
        "SELECT 1 FROM path_claims WHERE id = %s",
        (claim_id,),
    ).fetchone()
    assert (
        test_db.execute(
            "SELECT 1 FROM path_claim_task_bindings WHERE claim_id = %s",
            (claim_id,),
        ).fetchone()
        is None
    )


def test_no_task_intake_defers_gate_but_activation_remains_strict(test_db) -> None:
    item_id = seed_epic(test_db, item_id=21009, status="plan-drafted")

    gate = required_gate(test_db, item_id)

    assert gate["verdict"] == "pass"
    assert "defers" in str(gate["reason"])
    assert "no generated Epic tasks" in str(
        task_activation_block_reason(test_db, item_id)
    )


def test_real_pinned_policy_resolution_failure_blocks_gate(test_db) -> None:
    seed_epic(test_db, item_id=21010)
    source = test_db.execute(
        "SELECT definition_schema_version, definition_json "
        "FROM workflow_versions WHERE workflow_id = 'epic' "
        "ORDER BY version DESC LIMIT 1"
    ).fetchone()
    bad_version_id = int(
        test_db.execute(
            "INSERT INTO workflow_versions "
            "(workflow_id, version, definition_schema_version, definition_json, "
            "definition_digest, published_at, immutable_at) "
            "VALUES ('epic', 999, %s, %s, 'invalid', "
            "'2026-07-28T00:00:00Z', '2026-07-28T00:00:00Z') RETURNING id",
            (int(source[0]), str(source[1])),
        ).fetchone()[0]
    )
    item_id = 21011
    test_db.execute(
        "INSERT INTO items "
        "(id, title, workflow_id, workflow_version_id, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'Broken pin', 'epic', %s, 'idea', 'medium', "
        "'2026-07-28T00:00:00Z', '2026-07-28T00:00:00Z', 1, %s)",
        (item_id, bad_version_id, item_id),
    )
    test_db.commit()

    gate = required_gate(test_db, item_id)

    assert gate["verdict"] == "block"
    assert "unreadable pinned path-claim policy" in str(gate["reason"])
