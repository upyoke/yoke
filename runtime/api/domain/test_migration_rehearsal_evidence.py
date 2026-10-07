# ruff: noqa: F811

"""Rehearsal writes its receipt exactly where the evidence gate reads it."""

from __future__ import annotations

from yoke_core.domain.migration_apply import rehearse
from yoke_core.domain.migration_rehearsal_evidence import (
    module_rehearsed,
    receipt_writers,
)
from runtime.api.domain.migration_apply_test_helpers import (  # noqa: F401 — fixtures
    _seed_apply_item,
    apply_env,  # noqa: F401 — fixture registration
)
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401 — reused fixtures


def _rehearsed(control_db: str, *, project_id: int, model_name: str) -> bool:
    conn = _conn(control_db)
    try:
        return module_rehearsed(
            conn,
            project_id=project_id,
            model_name=model_name,
            identifier="sample_migration",
        )
    finally:
        conn.close()


def test_rehearse_receipt_is_what_the_gate_reader_finds(apply_env) -> None:
    control_db = apply_env["control_db"]
    _seed_apply_item(control_db, item_id=5101)
    assert not _rehearsed(control_db, project_id=1, model_name="primary")

    result = rehearse(
        5101,
        control_db_path=control_db,
        worktree_path=apply_env["worktree"],
    )

    assert result.all_succeeded
    assert _rehearsed(control_db, project_id=1, model_name="primary")


def test_receipt_is_scoped_to_its_project_and_model(apply_env) -> None:
    control_db = apply_env["control_db"]
    conn = _conn(control_db)
    try:
        insert_row, update_state = receipt_writers(conn)
        audit_id = insert_row(
            name="sample_migration",
            model_name="registry",
            project_id=2,
            session_id=None,
            test_copy_path=None,
            tables=[],
        )
        update_state(audit_id, "rehearsed")
    finally:
        conn.close()

    assert _rehearsed(control_db, project_id=2, model_name="registry")
    assert not _rehearsed(control_db, project_id=1, model_name="registry")
    assert not _rehearsed(control_db, project_id=2, model_name="primary")


def test_unsettled_receipt_is_not_evidence(apply_env) -> None:
    control_db = apply_env["control_db"]
    conn = _conn(control_db)
    try:
        insert_row, update_state = receipt_writers(conn)
        audit_id = insert_row(
            name="sample_migration",
            model_name="primary",
            project_id=1,
            session_id=None,
            test_copy_path=None,
            tables=[],
        )
        update_state(audit_id, "test_applied")
    finally:
        conn.close()

    assert not _rehearsed(control_db, project_id=1, model_name="primary")


def test_gate_refuses_then_passes_on_the_real_rehearsal_receipt(apply_env) -> None:
    """Neither side stubbed: the real rehearsal writes, the real gate reads."""
    from yoke_core.domain.db_mutation_gate import (
        check_implementing_to_reviewing_implementation_gate as gate,
    )

    control_db = apply_env["control_db"]
    _seed_apply_item(control_db, item_id=5102)

    conn = _conn(control_db)
    try:
        before = gate(5102, conn=conn)
    finally:
        conn.close()
    assert not before.passed
    assert any("no passing rehearsal receipt" in e for e in before.errors)

    result = rehearse(
        5102, control_db_path=control_db, worktree_path=apply_env["worktree"]
    )
    assert result.all_succeeded

    conn = _conn(control_db)
    try:
        after = gate(5102, conn=conn)
    finally:
        conn.close()
    assert after.passed, after.errors
