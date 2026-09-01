"""Backlog update operation — `execute_update` runs the canonical field
update path: builds the gate context, dispatches to the mutation layer,
verifies the status claim, runs the authoritative status / DB-mutation /
architecture / QA gates, applies the field writes, emits `ItemStatusChanged`,
cascades epic tasks, and triggers the post-DB GitHub sync side effects.
`execute_batch_update` applies the same field write across many items.
"""

from __future__ import annotations

import sys
from typing import Optional, TextIO

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.backlog_queries import (
    _assert_write_db_ready,
    _resolve_deploy_envs,
    _resolve_write_db_path,
)
from yoke_core.domain import backlog_rendering as _rendering
from yoke_core.domain.backlog_authoritative_status_gate import (
    _run_authoritative_status_gate,
)
from yoke_core.domain.backlog_batch_update import execute_batch_update
from yoke_core.domain.backlog_post_write_sync import run_post_db_sync
from yoke_core.domain.backlog_project_issue_migration import (
    _maybe_migrate_project_issue,
)
from yoke_core.domain.backlog_unsupported_field_writes import _apply_shell_fallback
from yoke_core.domain.backlog_status_claim_verification import _verify_status_claim
from yoke_core.domain.deployment_flow_validator import (
    normalize_deployment_flow_value,
    validate_and_lookup_flow_project,
)
from yoke_core.domain.item_block_notifications import (
    emit_item_block_state_change_if_needed,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.workflow_runtime import load_item_workflow_runtime


def _execute_update_once(
    item_id: int,
    field: str,
    value: str,
    resolution: Optional[str] = None,
    done_nonce_verified: bool = False,
    force: bool = False,
    qa_bypass: bool = False,
    session_id: Optional[str] = None,
    dry_run: bool = False,
    rebuild_board: bool = True,
    no_github: bool = False,
    out: TextIO = sys.stdout,
    expected_status: Optional[str] = None,
    originator_actor_id: Optional[int] = None,
) -> dict:
    """Validate, write, and execute side effects for one update attempt."""
    from yoke_core.domain import mutations

    db_path = _resolve_write_db_path()
    _assert_write_db_ready(db_path)
    conn = connect(db_path)
    sync_fail_count = 0

    try:
        validated_workflow_version_id = None
        validated_source_status = None
        approval_request_id = None
        if field == "status":
            from yoke_core.domain.workflow_status_transition_preflight import (
                prepare_status_transition,
            )

            preflight = prepare_status_transition(
                conn,
                item_id=item_id,
                target_status=value,
                originator_actor_id=originator_actor_id,
                session_id=session_id or "",
                expected_status=expected_status,
            )
            if preflight.failure is not None:
                return preflight.failure
            validated_workflow_version_id = preflight.workflow_version_id
            validated_source_status = preflight.source_status
            approval_request_id = preflight.approval_request_id
            from yoke_core.domain.backlog_status_write_precondition import (
                lock_status_write_precondition,
            )

            stale = lock_status_write_precondition(
                conn,
                item_id=item_id,
                observed_status=str(validated_source_status),
                observed_workflow_version_id=int(validated_workflow_version_id),
                expected_status=expected_status,
                expected_workflow_version_id=validated_workflow_version_id,
            )
            if stale is not None:
                return stale
        # Load item state
        row = conn.execute(
            "SELECT i.*, p.slug AS project FROM items i JOIN projects p ON p.id = i.project_id WHERE i.id = %s",
            (item_id,),
        ).fetchone()
        if row is None:
            return {
                "success": False,
                "error": f"Item {render_item_ref(conn, item_id)} not found",
            }

        flow_project = None
        if field == "deployment_flow":
            from yoke_core.domain.workflow_item_binding_lock import (
                lock_item_workflow_bindings,
            )

            value = normalize_deployment_flow_value(value)
            flow_project, flow_err = validate_and_lookup_flow_project(
                conn,
                value,
                dict(row).get("project"),
                lock_binding=True,
            )
            if flow_err:
                return {
                    "success": False,
                    "error": flow_err,
                    "error_code": "VALIDATION_ERROR",
                }
            lock_item_workflow_bindings(conn, (int(item_id),))
            row = conn.execute(
                "SELECT i.*, p.slug AS project FROM items i JOIN projects p ON p.id = i.project_id WHERE i.id = %s",
                (item_id,),
            ).fetchone()
            if row is None:
                return {
                    "success": False,
                    "error": f"Item {render_item_ref(conn, item_id)} not found",
                }

        item_dict = dict(row)
        workflow = load_item_workflow_runtime(conn, item_id)
        item_state = mutations.ItemState(
            id=item_dict["id"],
            public_ref=render_item_ref(conn, int(item_dict["id"])),
            title=item_dict["title"],
            status=item_dict["status"],
            priority=item_dict["priority"],
            frozen=bool(item_dict.get("frozen", 0)),
            blocked=bool(item_dict.get("blocked", 0)),
            blocked_reason=item_dict.get("blocked_reason"),
            project=item_dict.get("project"),
            deployment_flow=item_dict.get("deployment_flow"),
            deploy_stage=item_dict.get("deploy_stage"),
            deployed_to=item_dict.get("deployed_to"),
            merged_at=item_dict.get("merged_at"),
            workflow=workflow,
        )

        gate = mutations.GateContext(
            done_nonce_verified=done_nonce_verified,
            force=force,
            qa_bypass=qa_bypass,
        )
        if field == "deployment_flow":
            gate.flow_project = flow_project

        target_status = value if field == "status" else None
        if target_status and workflow.policies["generated_children"] == "epic_tasks":
            task_count_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM epic_tasks WHERE epic_id = %s",
                (item_dict["id"],),
            ).fetchone()
            gate.epic_task_count = task_count_row["cnt"] if task_count_row else 0

        if target_status:
            gate.has_merged_at = bool(item_dict.get("merged_at"))
            # The requirement count keeps the blocking scan off databases with
            # no QA rows at all, whose minimal schema need not carry every
            # column that scan reads.
            qa_req_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM qa_requirements WHERE item_id = %s",
                (item_dict["id"],),
            ).fetchone()
            if (qa_req_row["cnt"] if qa_req_row else 0) > 0:
                unsatisfied_all = conn.execute(
                    """SELECT COUNT(*) as cnt FROM qa_requirements qr
                       WHERE qr.item_id = %s AND qr.blocking_mode = 'blocking'
                       AND qr.waived_at IS NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM qa_runs qrun
                           WHERE qrun.qa_requirement_id = qr.id
                           AND qrun.verdict = 'pass'
                       )""",
                    (item_dict["id"],),
                ).fetchone()
                gate.unsatisfied_all_blocking = (
                    unsatisfied_all["cnt"] if unsatisfied_all else 0
                )

        # Deployed-to validation
        if field == "deployed_to" and value:
            item_project = item_dict.get("project") or "yoke"
            gate.valid_deploy_envs = _resolve_deploy_envs(conn, item_project)

        # Call mutation layer
        mutation_result = mutations.prepare_update(
            item=item_state,
            field_name=field,
            value=value,
            gate=gate,
        )

        if not mutation_result.success:
            error_code = mutation_result.error_code
            if error_code == "UNSUPPORTED_FIELD":
                # Narrow bridge for source, owner, deploy-stage, and
                # architecture-impact writes.
                return _apply_shell_fallback(conn, item_id, field, value, out)

            return {
                "success": False,
                "error": mutation_result.error or "Unknown error",
                "error_code": error_code,
            }
        if field == "status" and value == "cancelled":
            mutation_result.field_writes["resolution"] = resolution
        if field == "status":
            claim_verified, claim_reason = _verify_status_claim(conn, item_id, out, session_id=session_id)
            if not claim_verified:
                public_ref = render_item_ref(conn, item_id)
                return {
                    "success": False,
                    "error": (
                        f"Claim verification denied for {public_ref}: {claim_reason}\n"
                        f'  Claim first: yoke claims work acquire --item {public_ref} --reason "<intent>"\n'
                        f"  Incident recovery: yoke lifecycle repair-status {public_ref} "
                        f'--to {value} --reason "reconcile lifecycle state"\n'
                        "  Audit bypass: set YOKE_CLAIM_BYPASS=<source> for sanctioned system transitions"
                    ),
                }

        if field == "project":
            migrated, migration_error = _maybe_migrate_project_issue(conn, item_dict, value, out)
            if not migrated:
                return {
                    "success": False,
                    "error": migration_error or "Project issue migration failed",
                }

        if field == "status":
            authoritative_gate_result = _run_authoritative_status_gate(
                item_id=item_id,
                target_status=value,
                db_path=db_path,
                qa_bypass=qa_bypass,
                force=force,
                session_id=session_id,
                conn=conn,
            )
            if authoritative_gate_result is not None:
                return authoritative_gate_result

        old_status = item_dict["status"] if field == "status" else None
        from yoke_core.domain.backlog_status_write_precondition import (
            apply_prepared_item_writes,
        )

        stale = apply_prepared_item_writes(
            conn,
            item_id=item_id,
            field=field,
            value=value,
            item=item_dict,
            field_writes=mutation_result.field_writes,
            expected_status=expected_status,
            expected_workflow_version_id=validated_workflow_version_id,
        )
        if stale is not None:
            return stale

        from yoke_core.domain.backlog_update_effects import (
            run_post_commit_update_effects,
            run_transactional_update_effects,
        )

        effect_receipt = run_transactional_update_effects(
            conn,
            item_id=item_id,
            field=field,
            value=value,
            old_status=old_status,
            session_id=session_id,
            out=out,
            approval_request_id=approval_request_id,
            workflow_version_id=validated_workflow_version_id,
            actor_id=originator_actor_id,
        )
        if field == "status":
            conn.commit()
        print(f"Updated: {render_item_ref(conn, item_id)} {field} → {value}", file=out)
        run_post_commit_update_effects(
            conn,
            receipt=effect_receipt,
            out=out,
        )
        emit_item_block_state_change_if_needed(conn, item=item_dict, field=field, value=value, session_id=session_id)
    finally:
        conn.close()

    # Post-DB side effects (outside conn context to avoid holding locks)

    if not no_github:
        sync_fail_count = run_post_db_sync(
            item_id=item_id,
            field=field,
            value=value,
            old_status=old_status,
            out=out,
        )

    if sync_fail_count > 0:
        print(
            f"Note: {sync_fail_count} GitHub sync operation(s) failed — items may need resync",
            file=out,
        )

    _rendering._maybe_rebuild_board(rebuild_board, dry_run=dry_run, out=out)

    return {"success": True}


__all__ = ["_execute_update_once", "execute_batch_update"]
