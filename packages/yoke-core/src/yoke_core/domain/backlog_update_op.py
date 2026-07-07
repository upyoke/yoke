"""Backlog update operation — `execute_update` runs the canonical field
update path: builds the gate context, dispatches to the mutation layer,
verifies the status claim, runs the authoritative status / DB-mutation /
architecture / QA gates, applies the field writes, emits `ItemStatusChanged`,
cascades epic tasks, and triggers the post-DB GitHub sync side effects.
`execute_batch_update` applies the same field write across many items.
"""

from __future__ import annotations

import os
import sys
from typing import Optional, TextIO

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.backlog_queries import (
    LABEL_SYNC_FIELDS,
    _assert_write_db_ready,
    _resolve_deploy_envs,
    _resolve_write_db_path,
)
from yoke_core.domain import backlog_rendering as _rendering
from yoke_core.domain.backlog_authoritative_status_gate import (
    _run_authoritative_status_gate,
)
from yoke_core.domain.backlog_epic_task_cascade import _cascade_epic_tasks
from yoke_core.domain.backlog_item_db_writes import _update_item_multi
from yoke_core.domain.backlog_project_issue_migration import (
    _maybe_migrate_project_issue,
)
from yoke_core.domain.backlog_session_attribution import (
    _maybe_set_session_current_item,
)
from yoke_core.domain.backlog_unsupported_field_writes import _apply_shell_fallback
from yoke_core.domain.backlog_status_claim_verification import _verify_status_claim
from yoke_core.domain.deployment_flow_validator import normalize_deployment_flow_value, validate_and_lookup_flow_project


def execute_update(
    item_id: int,
    field: str,
    value: str,
    done_nonce_verified: bool = False,
    force: bool = False,
    qa_bypass: bool = False,
    session_id: Optional[str] = None,
    dry_run: bool = False,
    rebuild_board: bool = True,
    no_github: bool = False,
    out: TextIO = sys.stdout,
) -> dict:
    """Full item update: validate → UPDATE → side effects → sync.

    Caller-supplied gates such as done-nonce, force, and QA bypass are
    folded into the mutation-layer context before the write.

    Returns a result dict with 'success', 'error', etc.
    """
    from yoke_core.domain import mutations

    db_path = _resolve_write_db_path()
    _assert_write_db_ready(db_path)
    conn = connect(db_path)
    sync_fail_count = 0

    try:
        # Load item state
        row = conn.execute("SELECT i.*, p.slug AS project FROM items i JOIN projects p ON p.id = i.project_id WHERE i.id = %s", (item_id,)).fetchone()
        if row is None:
            return {"success": False, "error": f"Item YOK-{item_id} not found"}

        item_dict = dict(row)
        item_state = mutations.ItemState(
            id=item_dict["id"],
            title=item_dict["title"],
            item_type=item_dict["type"],
            status=item_dict["status"],
            priority=item_dict["priority"],
            rework_count=item_dict.get("rework_count", 0),
            frozen=bool(item_dict.get("frozen", 0)), blocked=bool(item_dict.get("blocked", 0)), blocked_reason=item_dict.get("blocked_reason"),
            project=item_dict.get("project"),
            deployment_flow=item_dict.get("deployment_flow"),
            deploy_stage=item_dict.get("deploy_stage"),
            deployed_to=item_dict.get("deployed_to"),
            worktree=item_dict.get("worktree"),
            merged_at=item_dict.get("merged_at"),
        )

        # Build gate context
        gate = mutations.GateContext(
            done_nonce_verified=done_nonce_verified,
            force=force,
            qa_bypass=qa_bypass,
        )

        target_status = value if field == "status" else None
        if target_status and item_dict["type"] == "epic":
            task_count_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM epic_tasks WHERE epic_id = %s",
                (item_dict["id"],),
            ).fetchone()
            gate.epic_task_count = task_count_row["cnt"] if task_count_row else 0

        if target_status:
            gate.has_merged_at = bool(item_dict.get("merged_at"))
            qa_req_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM qa_requirements WHERE item_id = %s",
                (item_dict["id"],),
            ).fetchone()
            gate.qa_requirement_count = qa_req_row["cnt"] if qa_req_row else 0

            if gate.qa_requirement_count > 0:
                unsatisfied_val = conn.execute(
                    """SELECT COUNT(*) as cnt FROM qa_requirements qr
                       WHERE qr.item_id = %s AND qr.qa_phase = 'verification'
                       AND qr.blocking_mode = 'blocking'
                       AND qr.waived_at IS NULL
                       AND NOT EXISTS (
                           SELECT 1 FROM qa_runs qrun
                           WHERE qrun.qa_requirement_id = qr.id
                           AND qrun.verdict = 'pass'
                       )""",
                    (item_dict["id"],),
                ).fetchone()
                gate.unsatisfied_verification_blocking = unsatisfied_val["cnt"] if unsatisfied_val else 0

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
                gate.unsatisfied_all_blocking = unsatisfied_all["cnt"] if unsatisfied_all else 0

        if field == "deployment_flow":
            value = normalize_deployment_flow_value(value)
            flow_project, flow_err = validate_and_lookup_flow_project(conn, value, item_dict.get("project"))
            if flow_err:
                return {"success": False, "error": flow_err, "error_code": "VALIDATION_ERROR"}
            gate.flow_project = flow_project

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
                # Narrow bridge for type, source, and deploy_stage writes.
                return _apply_shell_fallback(conn, item_id, field, value, out)

            return {
                "success": False,
                "error": mutation_result.error or "Unknown error",
                "error_code": error_code,
            }

        if field == "status":
            claim_verified, claim_reason = _verify_status_claim(
                conn, item_id, out, session_id=session_id)
            if not claim_verified:
                return {
                    "success": False,
                    "error": (
                        f"Claim verification denied for YOK-{item_id}: {claim_reason}\n"
                        f"  Claim first: python3 -m yoke_core.api.service_client claim-work --item YOK-{item_id}\n"
                        "  Incident recovery: python3 -m yoke_core.engines.repair_status (emits audit events)\n"
                        "  Audit bypass: set YOKE_CLAIM_BYPASS=<source> for sanctioned system transitions"
                    ),
                }

        if field == "project":
            migrated, migration_error = _maybe_migrate_project_issue(conn, item_dict, value, out)
            if not migrated:
                return {"success": False, "error": migration_error or "Project issue migration failed"}

        if field == "status":
            authoritative_gate_result = _run_authoritative_status_gate(
                item_id=item_id,
                target_status=value,
                db_path=db_path,
                qa_bypass=qa_bypass,
                force=force,
            )
            if authoritative_gate_result is not None:
                return authoritative_gate_result

        # Capture old status before applying writes
        old_status = item_dict["status"] if field == "status" else None

        # Apply field_writes from mutation result
        field_writes = mutation_result.field_writes
        filtered_writes = {
            k: v for k, v in field_writes.items()
            if k != "updated_at"  # The DB write helper owns updated_at.
        }

        if filtered_writes:
            _update_item_multi(conn, item_id, filtered_writes)

        print(f"Updated: YOK-{item_id} {field} → {value}", file=out)

        # Rework detection message
        for event in mutation_result.events:
            if event.kind.value == "rework_incremented":
                rw_count = event.detail.get("rework_count", "")
                if rw_count:
                    print(f"Rework detected: YOK-{item_id} rework_count → {rw_count}", file=out)

        # Record the transition (state) + emit ItemStatusChanged (telemetry)
        if field == "status" and old_status and old_status != value:
            from yoke_core.domain.item_status_transitions import (
                record_and_emit_item_status_change,
            )
            record_and_emit_item_status_change(
                conn,
                item_id=item_id,
                from_status=old_status,
                to_status=value,
                source=os.environ.get("YOKE_STATUS_SOURCE", "backlog-registry"),
                out=out,
            )

        # Epic task cascade
        if field == "status" and old_status and old_status != value:
            _cascade_epic_tasks(conn, item_id, old_status, value, out)
            _maybe_set_session_current_item(conn, item_id, session_id)

        if field == "status" and value in ("cancelled", "stopped", "release", "done"):
            try:
                if value in ("cancelled", "stopped"):
                    from yoke_core.domain.path_claims_item_hook import (
                        cancel_claims_on_item_terminal as _hook,
                    )
                    _verb = "Cancelled"
                elif (
                    value == "done"
                    or os.environ.get("YOKE_STATUS_SOURCE") == "done-transition"
                    or os.environ.get("YOKE_CLAIM_BYPASS", "").startswith("deploy-pipeline:")
                ):
                    from yoke_core.domain.path_claims_item_hook_release \
                        import release_claims_on_item_terminal as _hook
                    _verb = "Released"
                else:
                    _hook = None
                if _hook is not None:
                    _n = _hook(conn, item_id=item_id, new_status=value)
                    if _n:
                        print(f"{_verb} {_n} non-terminal path claim(s) "
                              f"for YOK-{item_id}", file=out)
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass

        if field == "status" and value == "done":
            print(f"Done cleanup: YOK-{item_id} frozen→false, blocked→false, worktree→null", file=out)
    finally:
        conn.close()

    # Post-DB side effects (outside conn context to avoid holding locks)

    if not no_github:
        # Auto-close GitHub issue
        if field == "status" and value in ("done", "cancelled"):
            # ``_close_issue`` owns the structured ``SyncFailed`` emit.
            if not _rendering._close_issue(item_id, out):
                sync_fail_count += 1

        # Sync labels
        if field in LABEL_SYNC_FIELDS:
            if not _rendering._sync_labels(item_id, out):
                sync_fail_count += 1
                _rendering._record_sync_failure(item_id, "labels", "sync_labels failed")

        # Sync title
        if field == "title":
            if not _rendering._sync_title(item_id, out):
                sync_fail_count += 1
                _rendering._record_sync_failure(item_id, "title", "sync_title failed")

        # Sync frozen / blocked boolean-flag labels (blocked added)
        if field in ("frozen", "blocked") and not getattr(_rendering, f"_sync_{field}_label")(item_id, value, out):
            sync_fail_count += 1
            _rendering._record_sync_failure(item_id, f"{field}-label", f"sync_{field}_label failed")

        # Post status-change comment
        if field == "status" and old_status and old_status != value:
            if not _rendering._post_comment(item_id, old_status, value, out):
                sync_fail_count += 1
                _rendering._record_sync_failure(item_id, "comment", "post_comment failed")

    if sync_fail_count > 0:
        print(f"Note: {sync_fail_count} GitHub sync operation(s) failed — items may need resync", file=out)

    _rendering._maybe_rebuild_board(rebuild_board, dry_run=dry_run, out=out)

    return {"success": True}


def execute_batch_update(
    item_ids: list[int],
    field: str,
    value: str,
    done_nonce_verified: bool = False,
    force: bool = False,
    qa_bypass: bool = False,
    session_id: Optional[str] = None,
    dry_run: bool = False,
    rebuild_board: bool = True,
    out: TextIO = sys.stdout,
) -> dict:
    """Apply one field update across multiple items."""
    updated_count = 0
    for item_id in item_ids:
        result = execute_update(
            item_id=item_id,
            field=field,
            value=value,
            done_nonce_verified=done_nonce_verified,
            force=force,
            qa_bypass=qa_bypass,
            session_id=session_id,
            dry_run=dry_run,
            rebuild_board=False,
            out=out,
        )
        if not result.get("success"):
            result = dict(result)
            result.setdefault("updated_count", updated_count)
            return result
        updated_count += 1

    _rendering._maybe_rebuild_board(rebuild_board, dry_run=dry_run, out=out)
    print(f"Batch updated {updated_count} item(s): {field} → {value}", file=out)
    return {"success": True, "updated_count": updated_count}

__all__ = ["execute_update", "execute_batch_update"]
