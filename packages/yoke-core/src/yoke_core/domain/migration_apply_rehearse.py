"""Rehearsal unit for governed migrations."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any, List, Optional
from yoke_contracts.schema_authority import serving_build_authority

from yoke_core.domain import db_helpers
from yoke_core.domain.db_compatibility_attestation import (
    _safe_parse_dict as _safe_parse_attestation,
)
from yoke_core.domain.schema_fingerprint import (
    UnsupportedFingerprintKindError,
)
from yoke_core.domain.migration_apply_audit import (
    _insert_audit_row,
    _update_audit_state,
)
from yoke_core.domain.migration_apply_targets import (
    connect_db_target,
    ensure_migration_audit_table_for_target,
    fingerprint_db_target,
)
from yoke_core.domain import migration_territory_claim
from yoke_core.domain.migration_apply_contract import (
    FAIL_TEST_APPLY,
    FAIL_TEST_VERIFY,
    STATE_PLANNED,
    STATE_REHEARSED,
    STATE_TEST_APPLIED,
    STATE_TEST_COPY_CREATED,
    STATE_TEST_VERIFIED,
    MigrationApplyError,
    ModuleAttemptResult,
    ModuleContractError,
    ModuleResolutionError,
    RehearseResult,
    _now,
)
from yoke_core.domain.migration_apply_resolve import (
    default_worktree_path,
    resolve_rehearsal_targets,
    resolve_runner_input,
)
from yoke_core.domain.migration_apply_runners import dispatch_handle
from yoke_core.domain.migration_apply_verify import (
    _append_rehearsal_outcomes,
    _row_count_map,
    _run_baseline_verify,
    _run_module_invariants,
    _run_rehearsal_commands,
)
from yoke_core.domain.migration_harness_checks import (
    pg_insert_migration_audit_row,
    pg_update_migration_audit_state,
)


def rehearse(
    item_id: int,
    *,
    session_id: Optional[str] = None,
    control_db_path: Optional[str] = None,
    worktree_path: Optional[Path] = None,
) -> RehearseResult:
    """Run the rehearsal unit for *item_id* on the model's validation surface.

    *session_id* is stamped on the audit row.  *control_db_path* overrides
    the control-plane DB lookup for tests; production callers leave it
    ``None`` and the canonical YOKE_DB wins.  *worktree_path* is the
    checkout root; defaults to the current working directory.

    The selected authority owns durable lease and audit receipts. Migration
    code executes only against a separately bound database whose live identity
    is verified as distinct from that authority.
    """
    control_conn = db_helpers.connect(control_db_path)
    try:
        return _rehearse_inner(
            control_conn,
            item_id=item_id,
            session_id=session_id,
            worktree_path=default_worktree_path(control_conn, item_id, worktree_path),
        )
    finally:
        control_conn.close()


def _rehearse_inner(
    control_conn: Any,
    *,
    item_id: Optional[int],
    session_id: Optional[str],
    worktree_path: Path,
) -> RehearseResult:
    resolved = resolve_runner_input(control_conn, item_id=item_id)
    profile = resolved.profile
    project = resolved.project
    project_id = resolved.project_id
    model, authoritative_db, validation_target, env_var = resolve_rehearsal_targets(
        control_conn, resolved, worktree_path
    )
    # Held past this call on purpose -- see migration_territory_claim.
    lease = migration_territory_claim.enter(
        control_conn,
        project=project,
        model_name=profile["model_name"],
        item_id=int(item_id),
        session_id=session_id,
    )

    affected_tables = sorted(
        {
            str(s.get("table") or "")
            for s in (profile.get("affected_surfaces") or [])
            if s.get("table")
        }
    )
    count_preserving = bool(profile.get("count_preserving", True))

    attestation = _safe_parse_attestation(resolved.attestation_raw) or {}
    rehearsal_commands = list(attestation.get("rehearsal_commands") or [])

    result = RehearseResult(
        lease_id=lease.id,
        item_id=item_id,
        model_name=profile["model_name"],
        validation_db_path=validation_target.display,
        source_fingerprint=None,
        rehearsed_at=None,
    )

    # Audit receipts belong to the model's authority, not the control plane.
    audit_conn = connect_db_target(authoritative_db)
    try:
        ensure_migration_audit_table_for_target(authoritative_db, audit_conn)
        if authoritative_db.kind == "postgres":
            insert_audit_row = partial(pg_insert_migration_audit_row, audit_conn)
            update_audit_state = partial(pg_update_migration_audit_state, audit_conn)
        else:
            insert_audit_row = partial(_insert_audit_row, audit_conn)
            update_audit_state = partial(_update_audit_state, audit_conn)
        # Compute pre-counts against the validation surface up front so
        # each module's baseline verify has a stable baseline.
        val_conn = connect_db_target(validation_target)
        try:
            pre_counts_validation = _row_count_map(val_conn, affected_tables)
        finally:
            val_conn.close()

        for identifier in profile["migration_modules"]:
            attempt = ModuleAttemptResult(
                identifier=identifier,
                audit_id=None,
                state=STATE_PLANNED,
            )
            result.modules.append(attempt)
            try:
                attempt.audit_id = insert_audit_row(
                    name=identifier,
                    model_name=profile["model_name"],
                    project_id=project_id,
                    session_id=session_id,
                    test_copy_path=validation_target.display,
                    tables=affected_tables,
                    description=None,
                )
                # test_copy_created
                update_audit_state(
                    attempt.audit_id,
                    STATE_TEST_COPY_CREATED,
                )
                attempt.state = STATE_TEST_COPY_CREATED

                # Apply only to the already verified distinct validation DB.
                try:
                    handle = dispatch_handle(
                        model=model,
                        repo_path=worktree_path,
                        identifier=identifier,
                        project=project,
                        model_name=profile["model_name"],
                    )
                except (
                    MigrationApplyError,
                    ModuleResolutionError,
                    ModuleContractError,
                ) as exc:
                    update_audit_state(
                        attempt.audit_id,
                        FAIL_TEST_APPLY,
                        extra={"failure_reason": str(exc)},
                    )
                    attempt.state = FAIL_TEST_APPLY
                    attempt.error = str(exc)
                    continue

                val_conn = connect_db_target(validation_target)
                try:
                    try:
                        with serving_build_authority():
                            handle.apply(val_conn)
                        val_conn.commit()
                    except Exception as exc:  # noqa: BLE001
                        update_audit_state(
                            attempt.audit_id,
                            FAIL_TEST_APPLY,
                            extra={"failure_reason": str(exc)},
                        )
                        attempt.state = FAIL_TEST_APPLY
                        attempt.error = f"module apply() raised on validation DB: {exc}"
                        continue
                    update_audit_state(
                        attempt.audit_id,
                        STATE_TEST_APPLIED,
                    )
                    attempt.state = STATE_TEST_APPLIED

                    # test_verified: baseline + invariants + rehearsal commands.
                    baseline_result, baseline_err = _run_baseline_verify(
                        val_conn,
                        affected_tables,
                        count_preserving,
                        pre_counts_validation,
                    )
                    invariant_err = _run_module_invariants(handle, val_conn)
                finally:
                    val_conn.close()

                verify_failures: List[str] = []
                if baseline_err:
                    verify_failures.append(baseline_err)
                if invariant_err:
                    verify_failures.append(invariant_err)

                outcomes, cmd_err = _run_rehearsal_commands(
                    rehearsal_commands,
                    env_var=env_var,
                    validation_db_path=validation_target.target,
                    cwd=worktree_path,
                )
                author_verify_result = {
                    "module_invariants": {"error": invariant_err},
                    "rehearsal_commands": outcomes,
                }
                if outcomes:
                    _append_rehearsal_outcomes(
                        control_conn,
                        item_id,
                        outcomes,
                    )
                if cmd_err:
                    verify_failures.append(cmd_err)

                if verify_failures:
                    update_audit_state(
                        attempt.audit_id,
                        FAIL_TEST_VERIFY,
                        extra={
                            "baseline_verify_result": json.dumps(baseline_result),
                            "author_verify_result": json.dumps(author_verify_result),
                            "failure_reason": "; ".join(verify_failures),
                        },
                    )
                    attempt.state = FAIL_TEST_VERIFY
                    attempt.error = "; ".join(verify_failures)
                    attempt.detail["baseline_verify_result"] = baseline_result
                    attempt.detail["author_verify_result"] = author_verify_result
                    continue

                update_audit_state(
                    attempt.audit_id,
                    STATE_TEST_VERIFIED,
                    extra={
                        "baseline_verify_result": json.dumps(baseline_result),
                        "author_verify_result": json.dumps(author_verify_result),
                    },
                )
                attempt.state = STATE_TEST_VERIFIED
                attempt.detail["baseline_verify_result"] = baseline_result
                attempt.detail["author_verify_result"] = author_verify_result

                # rehearsed: fingerprint authoritative DB, stamp rehearsed_at.
                try:
                    fingerprint = fingerprint_db_target(authoritative_db)
                except UnsupportedFingerprintKindError as exc:
                    update_audit_state(
                        attempt.audit_id,
                        FAIL_TEST_VERIFY,
                        extra={"failure_reason": str(exc)},
                    )
                    attempt.state = FAIL_TEST_VERIFY
                    attempt.error = str(exc)
                    continue
                rehearsed_at = _now()
                update_audit_state(
                    attempt.audit_id,
                    STATE_REHEARSED,
                    extra={
                        "source_fingerprint": fingerprint,
                        "rehearsed_at": rehearsed_at,
                    },
                )
                attempt.state = STATE_REHEARSED
                attempt.detail["source_fingerprint"] = fingerprint
                attempt.detail["rehearsed_at"] = rehearsed_at
                result.source_fingerprint = fingerprint
                result.rehearsed_at = rehearsed_at
            except Exception as exc:  # noqa: BLE001 — preserve partial state
                if attempt.audit_id is not None:
                    update_audit_state(
                        attempt.audit_id,
                        FAIL_TEST_VERIFY,
                        extra={"failure_reason": str(exc)},
                    )
                attempt.state = FAIL_TEST_VERIFY
                attempt.error = str(exc)
    finally:
        audit_conn.close()

    # A rehearsal that failed never entered migration territory, so it must
    # not leave the door locked behind it. A rehearsal that PASSED keeps the
    # claim: the item now owns this model until it lands or an operator
    # releases it (`yoke coordination-claim release`), which makes the
    # claim a visible signal rather than a momentary mutex.
    if not result.all_succeeded:
        result.lease_id = migration_territory_claim.leave(
            control_conn, lease.id, "rehearsal-failed"
        ).id

    return result
