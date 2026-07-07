#!/usr/bin/env python3
"""Yoke service client — thin CLI adapter for shell access to the domain layer.

This module provides a command-line interface that shell scripts and SKILL.md
flows can use to delegate correctness-critical decisions to the Python domain
layer instead of maintaining independent logic.

Read/decision commands:
    approve-check <flow-id> <current-stage>
        Validate whether a stage can be approved and return the next stage.
        Reads the deployment_flows table to get the flow's stages JSON.
        Exits 0 with next-stage on stdout if approval is valid.
        Exits 1 with error message on stderr if not.

    active-queue [--project P]
        Return the standard active-queue item list (non-done, non-cancelled,
        non-frozen) as pipe-delimited rows.  Delegates frozen/lifecycle
        semantics to the domain layer's ItemFilter and build_where_clause.

    classify-status <status> [--frozen 0|1] [--has-active-run 0|1]
        Return the board bucket for a given status/frozen/active-run combo.

    validate-status <status>
        Return 0 if status is a valid canonical item status, 1 if not.

    validate-transition <from-status> <to-status> [--item-type TYPE]
        Return 0 if the transition is a forward progression step, 1 if not.
        When --item-type is omitted, uses epic/default progression.

Mutation commands (return structured JSON for shell adapters to apply):
    create-item --title TITLE --type TYPE [--priority P] [--project P]
                [--deployment-flow F]
        Validate and prepare an item creation.  Returns JSON with
        field_writes, events, and defaults.  The shell adapter applies
        the DB insert and post-insert side effects.

    validate-update <item-id> --field FIELD --value VALUE
                [--done-nonce-verified] [--force] [--qa-bypass]
        Preflight only: validates and prepares a single-field item update.
        Returns JSON with preflight_only=true, field_writes, and events.
        Deprecated alias: update-item.

    item-next-id
        Return the next display ID (``YOK-N``) without side effects.

    execute-batch-update <field> <value> <item-id>...
        Apply one update across multiple items through the Python backlog domain.

    execute-update-cli <item-id> <update-args...>
        Parse the public backlog-registry update CLI shape in Python and
        delegate to execute_update / execute_structured_write.

    execute-create-cli [--dry-run] [--project P] [--deployment-flow F]
                       <title> <type> [status] [priority]
        Parse the public backlog-registry add CLI shape in Python and
        delegate to execute_create.

    execute-batch-update-cli <field=value> <item-id>...
        Parse the public backlog-registry batch-update CLI shape in Python
        and delegate to execute_batch_update.

    apply-approval <item-id>
        Validate and prepare an approval-apply mutation.  Returns JSON
        with next_stage, run_id, member_item_ids, and field_writes.

Environment:
    YOKE_DB  -- path to the SQLite database (required for DB-accessing commands)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root is importable when called from anywhere
_repo_root = str(Path(__file__).resolve().parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# ---------------------------------------------------------------------------
# Re-export all public symbols from child modules for backward compatibility.
# Any caller that does ``from yoke_core.api.service_client import X`` will
# continue to work without changes.
# ---------------------------------------------------------------------------

# Shared helpers, constants, base types
from yoke_core.api.service_client_shared import (  # noqa: F401
    _confirm_done_recovery,
    _consume_done_nonce,
    _emit_backlog_result,
    _get_db_path,
    _get_db_readonly,
    _get_db_readwrite,
    _isolated_test_mutation_error,
    _load_gate_context,
    _load_item_state,
    _load_routing_config,
    _mutation_result_to_dict,
    _normalize_yoke_root,
    _parse_item_id_arg,
    _repo_root,
    _resolve_deploy_envs,
    _resolve_session_id,
    _run_done_recovery,
    _shell_wrapper_mode,
    _subprocess_pythonpath,
    _table_exists,
    _update_requests_done,
    # Domain re-exports used by tests and callers
    AdapterCategory,
    ClaimedWork,
    FrontierItem,
    FrontierResult,
    FrontierState,
    SessionError,
    SessionOffer,
    approval,
    assess_post_delivery_drift,
    board,
    build_drift_review_failure_action,
    compute_domain_frontier,
    compute_schedule,
    config_path_from_db_path,
    decide_next_action,
    display_claim_item_id,
    domain_clean_stale,
    domain_end_session,
    domain_end_session_if_empty,
    domain_heartbeat,
    domain_read_checkpoint,
    domain_release_done_claims,
    domain_update_checkpoint,
    emit_drift_review_completed,
    emit_next_action_chosen,
    emit_post_decision_telemetry,
    evaluate_item_gate,
    get_max_chain_steps,
    lifecycle,
    load_routing_config,
    mutations,
    normalize_claim_item_id,
    plan_candidate_set,
    queries,
    read_chain_checkpoint,
    release_item_claim_for_execution,
    resolve_claimed_work_context,
    resolve_execution_lane,
    runs,
    session_offer_with_ownership,
    set_session_mode,
    should_emit_drift_review_checkpoint,
)

# Items-related query commands
from yoke_core.api.service_client_items import (  # noqa: F401
    _QI_ALL_FIELDS,
    _QI_DEFAULT_FIELDS,
    _QI_LARGE_TEXT_FIELDS,
    _QI_VIRTUAL_FIELDS,
    _parse_item_filters,
    _parse_item_id,
    _validate_fields,
    cmd_active_queue,
    cmd_classify_status,
    cmd_item_count,
    cmd_item_get,
    cmd_item_list,
    cmd_item_next_id,
    cmd_item_progress,
    cmd_item_render,
    cmd_item_row,
    cmd_validate_status,
    cmd_validate_transition,
)

# Sessions-related commands
from yoke_core.api.service_client_sessions import (  # noqa: F401
    _build_frontier_state_from_schedule,
    _validate_active_session,
    cmd_claim_release,
    cmd_clean_stale_sessions,
    cmd_harness_capabilities,
    cmd_release_all_claims,
    cmd_release_done_claims,
    cmd_session_begin,
    cmd_session_checkpoint,
    cmd_session_checkpoint_read,
    cmd_session_end,
    cmd_session_end_if_empty,
    cmd_session_heartbeat,
    cmd_session_offer,
    cmd_session_touch,
)
from yoke_core.api.service_client_work_claims import (  # noqa: F401
    WORK_CLAIM_COMMANDS,
    cmd_claim_work,
    cmd_release_work_claim,
)

# Board-related commands
from yoke_core.api.service_client_board import (  # noqa: F401
    _frontier_item_to_dict,
    _frontier_result_to_dict,
    _scheduled_step_to_dict,
    _scheduler_result_to_dict,
    cmd_charge_frontier,
    cmd_charge_schedule,
)

# Delivery/deployment/QA and backlog mutation commands
from yoke_core.api.service_client_delivery import (  # noqa: F401
    _blocker_detail_to_dict,
    cmd_apply_approval,
    cmd_approve_check,
    cmd_backlog_cli,
    cmd_backlog_dedup_search,
    cmd_backlog_github,
    cmd_backlog_list_cli,
    cmd_create_item,
    cmd_evaluate_gate,
    cmd_execute_batch_update,
    cmd_execute_batch_update_cli,
    cmd_execute_close,
    cmd_execute_create,
    cmd_execute_create_cli,
    cmd_execute_structured_write,
    cmd_execute_update,
    cmd_execute_update_cli,
    cmd_plan_candidates,
    cmd_update_item,
)

# Project Structure aggregate (path registry constitution)
from yoke_core.api.service_client_project_structure import (  # noqa: F401
    cmd_project_structure_get,
    cmd_project_structure_patch,
    cmd_project_structure_seed,
)

# Coordination-lease primitive
from yoke_core.api.service_client_coordination_leases import (  # noqa: F401
    COORDINATION_LEASE_COMMANDS,
    cmd_coordination_lease_acquire,
    cmd_coordination_lease_heartbeat,
    cmd_coordination_lease_list,
    cmd_coordination_lease_release,
)

# Unified DB-claim amendment workflow
from yoke_core.api.service_client_actors import (  # noqa: F401
    cmd_actors_get,
    cmd_actors_list,
)
from yoke_core.api.service_client_db_claim import (  # noqa: F401
    cmd_db_claim_amend,
)
from yoke_core.api.service_client_ouroboros import OUROBOROS_COMMANDS, cmd_field_note_log  # noqa: F401
from yoke_core.api.service_client_path_claims import PATH_CLAIMS_COMMANDS  # noqa: F401

# Runtime ownership guard for /yoke do resume dispatch
from yoke_core.api.service_client_ownership_guard import (  # noqa: F401
    OWNERSHIP_GUARD_COMMANDS,
    cmd_ownership_guard,
)

# Universal ``--help`` safety net (every subcommand exits 0 on --help).
from yoke_core.api.service_client_help import is_help_sub_arg, run_with_help_fallback  # noqa: F401


COMMANDS = {
    "approve-check": cmd_approve_check,
    "active-queue": cmd_active_queue,
    "item-next-id": cmd_item_next_id,
    "classify-status": cmd_classify_status,
    "validate-status": cmd_validate_status,
    "validate-transition": cmd_validate_transition,
    "create-item": cmd_create_item,
    "validate-update": cmd_update_item,
    "update-item": cmd_update_item,  # DEPRECATED: use validate-update
    "apply-approval": cmd_apply_approval,
    "session-offer": cmd_session_offer,
    "session-begin": cmd_session_begin,
    "session-touch": cmd_session_touch,
    "session-heartbeat": cmd_session_heartbeat,
    "session-end": cmd_session_end,
    "session-end-if-empty": cmd_session_end_if_empty,
    "session-checkpoint": cmd_session_checkpoint,
    "session-checkpoint-read": cmd_session_checkpoint_read,
    "harness-capabilities": cmd_harness_capabilities,
    "release-done-claims": cmd_release_done_claims,
    "clean-stale-sessions": cmd_clean_stale_sessions,
    "cleanup-never-engaged": cmd_clean_stale_sessions,  # deprecated alias
    "charge-frontier": cmd_charge_frontier,
    "charge-schedule": cmd_charge_schedule,
    "evaluate-gate": cmd_evaluate_gate,
    "plan-candidates": cmd_plan_candidates,
    "release-all-claims": cmd_release_all_claims,
    "claim-release": cmd_claim_release,
    **WORK_CLAIM_COMMANDS,
    "item-list": cmd_item_list,
    "item-count": cmd_item_count,
    "item-get": cmd_item_get,
    "item-row": cmd_item_row,
    "item-progress": cmd_item_progress,
    "backlog-dedup-search": cmd_backlog_dedup_search,
    "backlog-cli": cmd_backlog_cli,
    "backlog-list-cli": cmd_backlog_list_cli,
    "backlog-github": cmd_backlog_github,
    "execute-create-cli": cmd_execute_create_cli,
    "execute-create": cmd_execute_create,
    "execute-batch-update": cmd_execute_batch_update,
    "execute-batch-update-cli": cmd_execute_batch_update_cli,
    "execute-close": cmd_execute_close,
    "execute-update-cli": cmd_execute_update_cli,
    "execute-update": cmd_execute_update,
    "execute-structured-write": cmd_execute_structured_write,
    "project-structure-get": cmd_project_structure_get,
    "project-structure-patch": cmd_project_structure_patch,
    "project-structure-seed": cmd_project_structure_seed,
    **COORDINATION_LEASE_COMMANDS,
    "db-claim-amend": cmd_db_claim_amend,
    "actors-list": cmd_actors_list,
    "actors-get": cmd_actors_get,
    **PATH_CLAIMS_COMMANDS,
    **OWNERSHIP_GUARD_COMMANDS,
    **OUROBOROS_COMMANDS,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        from yoke_core.api.service_client_help_umbrella import render_umbrella_help
        print(render_umbrella_help(COMMANDS.keys()), end="")
        return 0
    cmd, sub_args = sys.argv[1], sys.argv[2:]
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(f"Available: {', '.join(COMMANDS.keys())}", file=sys.stderr)
        return 2
    if is_help_sub_arg(sub_args):
        return run_with_help_fallback(cmd, sub_args, COMMANDS[cmd])
    return COMMANDS[cmd](sub_args)


if __name__ == "__main__":
    sys.exit(main())
