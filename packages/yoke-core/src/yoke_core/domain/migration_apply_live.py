"""Live-apply unit for governed migrations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

from yoke_core.domain import db_helpers
from yoke_core.domain.coordination_leases import acquire_lease, get_lease, release_lease
from yoke_core.domain.db_mutation_gate_strategy import evaluate_strategy_matrix
from yoke_core.domain.migration_model_capability_defaults import resolve_model
from yoke_core.domain.projects_breakage_policy import BreakagePolicyError, resolve_breakage_policy
from yoke_core.domain.schema_fingerprint import FRESHNESS_WINDOW_MINUTES, freshness_expired
from yoke_core.domain.migration_apply_targets import (
    connect_db_target, create_rollback_backup,
    ensure_migration_audit_table_for_target, fingerprint_db_target,
    resolve_authoritative_db_target,
)
from yoke_core.domain.migration_apply_audit import (
    _latest_rehearsed_row, _update_audit_state,
    assert_live_apply_override_consistent,
    build_live_apply_provenance, set_audit_provenance,
)
from yoke_core.domain.migration_apply_contract import (
    FAIL_BACKUP, FAIL_LIVE_APPLY, FAIL_LIVE_VERIFY, LEASE_KEY_PREFIX,
    STATE_BACKUP_CREATED, STATE_COMPLETED, STATE_LIVE_APPLIED,
    STATE_LIVE_VERIFIED, STATE_REHEARSED, CompatibilityClassError,
    LiveApplyResult, MigrationApplyError, ModuleAttemptResult,
    ModuleContractError, ModuleResolutionError, RehearsalMissingError,
    RehearsalStaleError, _now,
)
from yoke_core.domain.migration_apply_resolve import (
    ModuleOverrideResolution, _load_item, _resolve_capability_settings,
    _resolve_profile_or_raise, _resolve_repo_path, default_worktree_path,
)
from yoke_core.domain.migration_apply_runners import dispatch_handle
from yoke_core.domain.migration_apply_verify import _row_count_map, _run_baseline_verify, _run_module_invariants
from yoke_core.domain.migration_auto_retire import auto_retire_after_live_apply
from yoke_core.domain.migration_harness_checks import (
    pg_latest_rehearsed_migration_audit_row as pg_latest,
    pg_set_migration_audit_provenance as pg_set_provenance,
    pg_update_migration_audit_state as pg_update_state,
)

def live_apply(
    item_id: int,
    *,
    session_id: Optional[str] = None,
    control_db_path: Optional[str] = None,
    worktree_path: Optional[Path] = None,
    module_override: Optional[ModuleOverrideResolution] = None,
) -> LiveApplyResult:
    """Run the live-apply unit for *item_id* against the model's authoritative DB.

    Requires a successful, fresh rehearsal.  Acquires
    ``LIVE_DB_MIGRATION:<model_name>`` for the duration of the live
    unit; releases it on success or failure with a structured reason.
    *module_override*, when supplied, must match the override recorded
    by rehearse — otherwise live-apply refuses rather than falling back
    to main.
    """
    control_conn = db_helpers.connect(control_db_path)
    try:
        return _live_apply_inner(
            control_conn,
            item_id=item_id,
            session_id=session_id or "live-apply",
            worktree_path=default_worktree_path(control_conn, item_id, worktree_path),
            module_override=module_override,
        )
    finally:
        control_conn.close()


def _live_apply_inner(
    control_conn: Any,
    *,
    item_id: int,
    session_id: str,
    worktree_path: Path,
    module_override: Optional[ModuleOverrideResolution] = None,
) -> LiveApplyResult:
    item = _load_item(control_conn, item_id)
    profile = _resolve_profile_or_raise(item)
    project = str(item.get("project") or "")
    if not project:
        raise MigrationApplyError(
            f"Item YOK-{item_id} has no project; cannot resolve model"
        )
    project_id = int(item["project_id"])
    try:
        breakage_policy = resolve_breakage_policy(control_conn, project)
    except BreakagePolicyError as exc:
        raise CompatibilityClassError(str(exc)) from exc
    matrix_errors = evaluate_strategy_matrix(
        breakage_policy=breakage_policy, profile=profile,
    )
    if matrix_errors:
        raise CompatibilityClassError(
            f"Item YOK-{item_id} fails the governed-runner gate matrix on "
            f"breakage_policy={breakage_policy!r}: {'; '.join(matrix_errors)}"
        )

    capability = _resolve_capability_settings(control_conn, project)
    try:
        model = resolve_model(capability, profile["model_name"])
    except KeyError as exc:
        raise MigrationApplyError(
            f"model '{profile['model_name']}' not declared on project '{project}'"
        ) from exc

    repo_path = _resolve_repo_path(control_conn, project)
    authoritative_db = resolve_authoritative_db_target(repo_path, model)

    result = LiveApplyResult(
        item_id=item_id,
        model_name=profile["model_name"],
        authoritative_db_path=authoritative_db.display,
        lease_id=None,
    )

    audit_conn = connect_db_target(authoritative_db)
    try:
        ensure_migration_audit_table_for_target(authoritative_db, audit_conn)
        if authoritative_db.kind == "postgres":
            latest_rehearsed_row = lambda *a: pg_latest(
                audit_conn, *a, project_id=project_id
            )
            set_audit_provenance_for_target = lambda *a: pg_set_provenance(audit_conn, *a)
            update_audit_state = lambda *a, **kw: pg_update_state(audit_conn, *a, **kw)
        else:
            latest_rehearsed_row = lambda *a: _latest_rehearsed_row(
                audit_conn, *a, project_id=project_id
            )
            set_audit_provenance_for_target = lambda *a: set_audit_provenance(audit_conn, *a)
            update_audit_state = lambda *a, **kw: _update_audit_state(audit_conn, *a, **kw)
        # Step 1: freshness/fingerprint gate BEFORE lease acquisition.
        current_fingerprint = fingerprint_db_target(authoritative_db)
        rehearsed_rows = []
        for identifier in profile["migration_modules"]:
            row = latest_rehearsed_row(identifier, profile["model_name"])
            if row is None:
                raise RehearsalMissingError(
                    f"module '{identifier}': no rehearsed audit row found on "
                    f"{authoritative_db.display}. Run migration-apply rehearse first."
                )
            if row.get("source_fingerprint") != current_fingerprint:
                raise RehearsalStaleError(
                    f"module '{identifier}': rehearsal fingerprint does not "
                    f"match authoritative DB — re-rehearse"
                )
            if freshness_expired(row.get("rehearsed_at")):
                raise RehearsalStaleError(
                    f"module '{identifier}': rehearsal older than "
                    f"{FRESHNESS_WINDOW_MINUTES}m window — re-rehearse"
                )
            assert_live_apply_override_consistent(
                identifier=identifier,
                audit_description=row.get("description"),
                override=module_override,
            )
            rehearsed_rows.append((identifier, row))

        # Step 2: acquire the per-model lease.  LeaseHeldError propagates
        # to the caller — no silent retry.
        lease_key = f"{LEASE_KEY_PREFIX}{profile['model_name']}"
        provenance = build_live_apply_provenance(
            control_conn=control_conn,
            session_id=session_id,
            worktree_path=worktree_path,
            profile=profile,
        )
        lease = acquire_lease(
            control_conn, project, lease_key, session_id,
            actor_id=provenance.get("actor_id"),
        )
        result.lease_id = lease.id

        affected_tables = sorted({
            str(s.get("table") or "")
            for s in (profile.get("affected_surfaces") or [])
            if s.get("table")
        })
        count_preserving = bool(profile.get("count_preserving", True))

        release_reason = "live-apply-complete"
        try:
            for identifier, rehearsed_row in rehearsed_rows:
                attempt = ModuleAttemptResult(
                    identifier=identifier,
                    audit_id=int(rehearsed_row["id"]),
                    state=STATE_REHEARSED,
                )
                result.modules.append(attempt)
                audit_id = attempt.audit_id

                # Stamp accountable provenance onto the audit row up front
                # so backup-failed and live-apply-failed paths also carry it.
                set_audit_provenance_for_target(audit_id, provenance)

                # backup_created — backup the authoritative DB.
                try:
                    backup_path = create_rollback_backup(
                        authoritative_db,
                        f"pre-live-apply-{identifier}",
                        worktree_path=worktree_path,
                    )
                except Exception as exc:  # noqa: BLE001
                    update_audit_state(
                        audit_id, FAIL_BACKUP,
                        extra={
                            "failure_reason": f"backup failed: {exc}",
                            "lease_id": result.lease_id,
                        },
                    )
                    attempt.state = FAIL_BACKUP
                    attempt.error = f"backup failed: {exc}"
                    release_reason = f"backup-failed: {identifier}"
                    break
                update_audit_state(
                    audit_id, STATE_BACKUP_CREATED,
                    extra={
                        "backup_path": backup_path,
                        "lease_id": result.lease_id,
                    },
                )
                attempt.state = STATE_BACKUP_CREATED
                attempt.detail["backup_path"] = backup_path

                # live_applied — apply module to authoritative DB.
                try:
                    handle = dispatch_handle(
                        model=model, repo_path=worktree_path,
                        identifier=identifier, override=module_override,
                        project=project, model_name=profile["model_name"],
                    )
                except (ModuleResolutionError, ModuleContractError) as exc:
                    update_audit_state(
                        audit_id, FAIL_LIVE_APPLY,
                        extra={"failure_reason": str(exc)},
                    )
                    attempt.state = FAIL_LIVE_APPLY
                    attempt.error = str(exc)
                    release_reason = f"live-apply-failed: {identifier}"
                    break

                live_conn = connect_db_target(authoritative_db)
                try:
                    pre_counts_live = _row_count_map(live_conn, affected_tables)
                    try:
                        handle.apply(live_conn)
                        live_conn.commit()
                    except Exception as exc:  # noqa: BLE001
                        update_audit_state(
                            audit_id, FAIL_LIVE_APPLY,
                            extra={
                                "failure_reason": (
                                    f"module apply() raised on authoritative "
                                    f"DB: {exc}"
                                ),
                            },
                        )
                        attempt.state = FAIL_LIVE_APPLY
                        attempt.error = f"module apply() raised: {exc}"
                        release_reason = f"live-apply-failed: {identifier}"
                        break
                    update_audit_state(
                        audit_id, STATE_LIVE_APPLIED,
                    )
                    attempt.state = STATE_LIVE_APPLIED

                    # live_verified — baseline + author invariants on live DB.
                    baseline_result, baseline_err = _run_baseline_verify(
                        live_conn,
                        affected_tables,
                        count_preserving,
                        pre_counts_live,
                    )
                    invariant_err = _run_module_invariants(handle, live_conn)
                finally:
                    live_conn.close()

                verify_failures: List[str] = []
                if baseline_err:
                    verify_failures.append(baseline_err)
                if invariant_err:
                    verify_failures.append(invariant_err)
                if verify_failures:
                    update_audit_state(
                        audit_id, FAIL_LIVE_VERIFY,
                        extra={
                            "baseline_verify_result": json.dumps(baseline_result),
                            "failure_reason": "; ".join(verify_failures),
                        },
                    )
                    attempt.state = FAIL_LIVE_VERIFY
                    attempt.error = "; ".join(verify_failures)
                    attempt.detail["baseline_verify_result"] = baseline_result
                    release_reason = f"live-verify-failed: {identifier}"
                    break

                update_audit_state(
                    audit_id, STATE_LIVE_VERIFIED,
                    extra={
                        "baseline_verify_result": json.dumps(baseline_result),
                    },
                )
                attempt.state = STATE_LIVE_VERIFIED
                attempt.detail["baseline_verify_result"] = baseline_result

                update_audit_state(
                    audit_id, STATE_COMPLETED,
                    extra={"completed_at": _now()},
                )
                attempt.state = STATE_COMPLETED
        finally:
            release_lease(control_conn, lease.id, release_reason)
            # Re-read the lease row so the caller sees the final state.
            result.lease_id = get_lease(control_conn, lease.id).id

        if all(m.state == STATE_COMPLETED for m in result.modules):
            modules_dir_rel = Path(
                str(model.get("runner", {}).get("config", {})
                    .get("modules_dir") or "")
            )
            if str(modules_dir_rel):
                auto_retire_after_live_apply(
                    audit_conn=audit_conn,
                    project=project,
                    model=model,
                    profile=profile,
                    worktree_path=worktree_path,
                    modules_dir_rel=modules_dir_rel,
                    item_id=item_id,
                )
    finally:
        audit_conn.close()

    return result
