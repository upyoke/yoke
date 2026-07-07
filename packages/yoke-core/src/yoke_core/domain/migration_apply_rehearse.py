"""Rehearsal unit for governed migrations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

from yoke_core.domain import db_helpers
from yoke_core.domain.db_compatibility_attestation import (
    _safe_parse_dict as _safe_parse_attestation,
)
from yoke_core.domain.db_mutation_gate_strategy import evaluate_strategy_matrix
from yoke_core.domain.migration_model_capability_defaults import resolve_model
from yoke_core.domain.projects_breakage_policy import (
    BreakagePolicyError,
    resolve_breakage_policy,
)
from yoke_core.domain.schema_fingerprint import (
    UnsupportedFingerprintKindError,
)
from yoke_core.domain.migration_apply_audit import (
    _insert_audit_row, _update_audit_state, describe_override,
)
from yoke_core.domain.migration_apply_targets import (
    connect_db_target, ensure_migration_audit_table_for_target,
    fingerprint_db_target, resolve_authoritative_db_target,
    resolve_connection_env_var, resolve_validation_db_target,
)
from yoke_core.domain.migration_apply_contract import (
    FAIL_TEST_APPLY, FAIL_TEST_VERIFY, STATE_PLANNED, STATE_REHEARSED,
    STATE_TEST_APPLIED, STATE_TEST_COPY_CREATED, STATE_TEST_VERIFIED,
    CompatibilityClassError, MigrationApplyError, ModuleAttemptResult,
    ModuleContractError, ModuleResolutionError, RehearseResult, _now,
)
from yoke_core.domain.migration_apply_resolve import (
    ModuleOverrideResolution, _load_item, _resolve_capability_settings,
    _resolve_profile_or_raise, _resolve_repo_path, control_conn_db_path,
    default_worktree_path,
)
from yoke_core.domain.migration_apply_runners import dispatch_handle
from yoke_core.domain.migration_apply_verify import (
    _append_rehearsal_outcomes, _row_count_map, _run_baseline_verify,
    _run_module_invariants, _run_rehearsal_commands,
)
from yoke_core.domain.migration_harness_checks import (
    pg_insert_migration_audit_row, pg_update_migration_audit_state,
)

def rehearse(
    item_id: int,
    *,
    session_id: Optional[str] = None,
    control_db_path: Optional[str] = None,
    worktree_path: Optional[Path] = None,
    module_override: Optional[ModuleOverrideResolution] = None,
) -> RehearseResult:
    """Run the rehearsal unit for *item_id* on the model's validation surface.

    *session_id* is stamped on the audit row.  *control_db_path* overrides
    the control-plane DB lookup for tests; production callers leave it
    ``None`` and the canonical YOKE_DB wins.  *worktree_path* is the
    checkout root; defaults to the current working directory.
    *module_override*, when supplied, sources the matching module from
    the active item worktree instead of the model's modules_dir
    through the sanctioned cross-worktree apply contract.
    """
    control_conn = db_helpers.connect(control_db_path)
    try:
        return _rehearse_inner(
            control_conn,
            item_id=item_id,
            session_id=session_id,
            worktree_path=default_worktree_path(control_conn, item_id, worktree_path),
            module_override=module_override,
        )
    finally:
        control_conn.close()


def _rehearse_inner(
    control_conn: Any,
    *,
    item_id: int,
    session_id: Optional[str],
    worktree_path: Path,
    module_override: Optional[ModuleOverrideResolution] = None,
) -> RehearseResult:
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
    env_var = resolve_connection_env_var(model)

    validation_target = resolve_validation_db_target(
        worktree_path=worktree_path,
        project=project,
        model_name=profile["model_name"],
        model=model,
        control_db_path=control_conn_db_path(control_conn),
    )

    affected_tables = sorted({
        str(s.get("table") or "")
        for s in (profile.get("affected_surfaces") or [])
        if s.get("table")
    })
    count_preserving = bool(profile.get("count_preserving", True))

    attestation = _safe_parse_attestation(
        item.get("db_compatibility_attestation")
    ) or {}
    rehearsal_commands = list(attestation.get("rehearsal_commands") or [])

    result = RehearseResult(
        item_id=item_id,
        model_name=profile["model_name"],
        validation_db_path=validation_target.display,
        source_fingerprint=None,
        rehearsed_at=None,
    )

    # Audit rows live on the MODEL's authoritative DB, not the
    # control-plane DB. ensure_migration_audit_table bootstraps the
    # table on first apply against a non-Yoke project's authoritative DB.
    audit_conn = connect_db_target(authoritative_db)
    try:
        ensure_migration_audit_table_for_target(authoritative_db, audit_conn)
        if authoritative_db.kind == "postgres":
            insert_audit_row = (
                lambda **kw: pg_insert_migration_audit_row(audit_conn, **kw)
            )
            update_audit_state = lambda *a, **kw: pg_update_migration_audit_state(
                audit_conn, *a, **kw,
            )
        else:
            insert_audit_row = lambda **kw: _insert_audit_row(audit_conn, **kw)
            update_audit_state = lambda *a, **kw: _update_audit_state(
                audit_conn, *a, **kw,
            )
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
            override_matches = (
                module_override is not None
                and module_override.slug == identifier
            )
            audit_description = (
                describe_override(module_override)
                if override_matches and module_override is not None
                else None
            )

            try:
                attempt.audit_id = insert_audit_row(
                    name=identifier,
                    model_name=profile["model_name"],
                    project_id=project_id,
                    session_id=session_id,
                    test_copy_path=validation_target.display,
                    tables=affected_tables,
                    description=audit_description,
                )
                if override_matches and module_override is not None:
                    attempt.detail["override_source"] = str(
                        module_override.source_path
                    )
                    attempt.detail["override_worktree"] = str(
                        module_override.worktree_path
                    )
                # test_copy_created
                update_audit_state(
                    attempt.audit_id, STATE_TEST_COPY_CREATED,
                )
                attempt.state = STATE_TEST_COPY_CREATED

                # test_applied: import + apply module against validation DB.
                try:
                    handle = dispatch_handle(
                        model=model, repo_path=worktree_path,
                        identifier=identifier, override=module_override,
                        project=project, model_name=profile["model_name"],
                    )
                except (ModuleResolutionError, ModuleContractError) as exc:
                    update_audit_state(
                        attempt.audit_id, FAIL_TEST_APPLY,
                        extra={"failure_reason": str(exc)},
                    )
                    attempt.state = FAIL_TEST_APPLY
                    attempt.error = str(exc)
                    continue

                val_conn = connect_db_target(validation_target)
                try:
                    try:
                        handle.apply(val_conn)
                        val_conn.commit()
                    except Exception as exc:  # noqa: BLE001
                        update_audit_state(
                            attempt.audit_id, FAIL_TEST_APPLY,
                            extra={"failure_reason": str(exc)},
                        )
                        attempt.state = FAIL_TEST_APPLY
                        attempt.error = (
                            f"module apply() raised on validation DB: {exc}"
                        )
                        continue
                    update_audit_state(
                        attempt.audit_id, STATE_TEST_APPLIED,
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
                        control_conn, item_id, outcomes,
                    )
                if cmd_err:
                    verify_failures.append(cmd_err)

                if verify_failures:
                    update_audit_state(
                        attempt.audit_id, FAIL_TEST_VERIFY,
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
                    attempt.audit_id, STATE_TEST_VERIFIED,
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
                        attempt.audit_id, FAIL_TEST_VERIFY,
                        extra={"failure_reason": str(exc)},
                    )
                    attempt.state = FAIL_TEST_VERIFY
                    attempt.error = str(exc)
                    continue
                rehearsed_at = _now()
                update_audit_state(
                    attempt.audit_id, STATE_REHEARSED,
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
                        attempt.audit_id, FAIL_TEST_VERIFY,
                        extra={"failure_reason": str(exc)},
                    )
                attempt.state = FAIL_TEST_VERIFY
                attempt.error = str(exc)
    finally:
        audit_conn.close()

    return result
