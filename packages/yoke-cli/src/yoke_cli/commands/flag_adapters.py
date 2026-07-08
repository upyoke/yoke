"""Per-family flag adapters for the ``yoke`` operations CLI.

This module is the thin facade. Per-family adapter functions live in
sibling ``yoke_cli.commands.adapters.<family>`` modules to keep each authored
file under the 350-line cap; the import list below is the authoritative
family roster (shared argparse/dispatch plumbing lives in
:mod:`yoke_cli.commands._helpers`; the function-id -> usage-line map
lives in :mod:`yoke_cli.commands.adapters.usage`).

Each adapter parses one family's flags via :mod:`argparse`, builds the
matching :class:`FunctionCallRequest` payload + :class:`TargetRef`, and
dispatches over the active transport via the shared helpers — https
relay, or in-process through
:func:`yoke_core.domain.yoke_function_dispatch.dispatch` on a local
universe.

Adapters return an int exit code. Stdout carries the canonical JSON
response on success; stderr carries error JSON on failure. ``--json``
forces the full :class:`FunctionCallResponse` envelope on stdout
regardless of outcome — useful for diagnostic tooling.

Session / actor identity:
    Every adapter accepts ``--session-id`` as an operator-debug override
    and otherwise resolves the active session through ``build_actor``
    (canonical ambient chain: env vars, then the hook-written
    process-anchor registry — ``session_ambient_identity``).
    ``actor_id`` is filled server-side from ``harness_sessions``; the
    CLI never fabricates one.
"""

from __future__ import annotations

from yoke_cli.commands.adapters.claims import (
    claims_path_register, claims_path_widen,
    claims_work_acquire, claims_work_release,
)
from yoke_cli.commands.adapters.organizations import organizations_get
from yoke_cli.commands.adapters.identity import (
    identity_autojoin_set,
    identity_invite_create,
    identity_invite_list,
    identity_invite_revoke,
    identity_link_set,
)
from yoke_cli.commands.adapters.claims_path_flow import (
    claims_path_activation_run,
    claims_path_required_gate,
)
from yoke_cli.commands.adapters.readiness import (
    readiness_check,
    readiness_prd_validate,
    readiness_repair_claim_coverage,
    readiness_repair_stale_count,
)
from yoke_cli.commands.adapters.items import (
    items_get,
    items_progress_log_append,
    items_structured_field_replace,
    lifecycle_skip_record_recoverable_substrate,
    lifecycle_transition,
)
from yoke_cli.commands.adapters.items_create import items_create
from yoke_cli.commands.adapters.items_scalar import items_scalar_update
from yoke_cli.commands.adapters.items_github_sync import (
    items_github_sync,
)
from yoke_cli.commands.adapters.items_section import (
    items_section_delete,
    items_section_get,
    items_section_upsert,
    items_structured_field_append_addendum,
    items_structured_field_section_append,
    items_structured_field_section_upsert,
)
from yoke_cli.commands.adapters.claims_read import (
    claims_path_get,
    claims_path_coordination_decision_build,
    claims_path_list,
    claims_work_current,
    claims_work_holder_get,
    claims_work_holder_list,
    path_claims_conflicts_list,
)
from yoke_cli.commands.adapters.db_claim import (
    db_claim_amend,
)
from yoke_cli.commands.adapters.db import db_read
from yoke_cli.commands.adapters.render import (
    agents_render,
    agents_render_check,
    board_data_get,
    packets_check,
    packets_render,
)
from yoke_cli.commands.adapters.board import board_rebuild
from yoke_cli.commands.adapters.epic_task import (
    epic_task_add,
    epic_task_body_replace,
    epic_task_metadata_update,
    epic_task_reassign,
    epic_task_remove,
    epic_task_split,
)
from yoke_cli.commands.adapters.epic_progress import (
    epic_progress_note_append,
    epic_progress_note_list,
    epic_tasks_list,
)
from yoke_cli.commands.adapters.epic_review import (
    epic_task_review_get,
    epic_task_review_insert, epic_task_review_list, epic_task_review_seed,
)
from yoke_cli.commands.adapters.epic_state import (
    epic_task_body_get,
    epic_task_simulation_upsert, epic_task_submission_receipt_get,
    epic_task_update_status,
)
from yoke_cli.commands.adapters.qa import (
    qa_requirement_waive,
    qa_requirement_auto_create_for_item,
    qa_requirement_update,
    qa_run_record_verdict,
)
from yoke_cli.commands.adapters.qa_browser import (
    qa_artifact_add,
    qa_artifact_presign,
    qa_browser_context_get,
    qa_run_add,
    qa_run_complete,
    qa_screenshot_evidence_pending_count,
    qa_screenshot_evidence_satisfy,
)
from yoke_cli.commands.adapters.qa_crud import (
    qa_requirement_add, qa_requirement_add_batch,
)
from yoke_cli.commands.adapters.qa_read import (
    qa_gate_summary,
    qa_requirement_get, qa_requirement_list, qa_run_get, qa_run_list,
)
from yoke_cli.commands.adapters.doctor import (
    doctor_run,
)
from yoke_cli.commands.adapters.deployment import (
    deployment_flows_get,
    deployment_flows_stages,
    deployment_runs_get,
    deployment_runs_list,
    deployment_runs_resolve_target_env,
    deployment_runs_update,
)
from yoke_cli.commands.adapters.ephemeral_env import ephemeral_env_update
from yoke_cli.commands.adapters.projects import (
    project_structure_patch_apply,
    projects_capability_has,
    projects_checkout_context,
    projects_get,
    projects_list,
    projects_resolve_by_github_repo,
)
from yoke_cli.commands.adapters.projects_write import (
    projects_create,
    projects_update,
)
from yoke_cli.commands.adapters.project_structure_read import (
    project_structure_command_definitions_get,
    project_structure_command_definitions_list,
    project_structure_deploy_defaults_get,
)
from yoke_cli.commands.adapters.projects_secret import (
    projects_capability_secret_set,
)
from yoke_cli.commands.adapters.github import (
    github_connect,
    github_pr_create,
    github_status,
)
from yoke_cli.commands.adapters.github_actions import (
    github_actions_check_ci,
    github_actions_secret_set,
    github_actions_variable_get,
    github_actions_variable_set,
)
from yoke_cli.commands.adapters.github_actions_run_wait import (
    github_actions_wait_run,
)
from yoke_cli.commands.adapters.strategy import (
    strategy_doc_archive,
    strategy_doc_get,
    strategy_doc_list,
    strategy_doc_replace,
    strategy_doc_unarchive,
)
from yoke_cli.commands.adapters.strategy_create import (
    strategy_doc_create,
)
from yoke_cli.commands.adapters.strategy_render import (
    strategy_ingest,
    strategy_render,
    strategy_seed_defaults,
)
from yoke_cli.commands.adapters.strategy_ops import (
    strategy_carry_candidate_set,
    strategy_carry_mark,
    strategy_carry_register_new,
    strategy_carry_summary,
    strategy_checkpoint_latest,
    strategy_checkpoint_record,
    strategy_master_plan_check,
)
from yoke_cli.commands.adapters.hooks import (
    hook_evaluate,
)
from yoke_cli.commands.adapters.events import (
    events_emit,
    events_anomalies,
    events_count,
    events_query,
    events_tail,
)
from yoke_cli.commands.adapters.listing import (
    items_list,
    items_search,
    shepherd_dependency_list,
)
from yoke_cli.commands.adapters.shepherd_dependency import (
    shepherd_dependency_add,
    shepherd_dependency_remove,
    shepherd_dependency_update,
)
from yoke_cli.commands.adapters.shepherd_writes import (
    shepherd_caveat_disposition,
    shepherd_verdict,
)
from yoke_cli.commands.adapters.misc import (
    ouroboros_entry_get,
    ouroboros_entry_list,
    ouroboros_field_note_append,
    ouroboros_field_note_get,
    ouroboros_field_note_list,
    scratch_dispatch_inputs,
)
from yoke_cli.commands.adapters.ouroboros_writes import (
    ouroboros_entry_insert,
    ouroboros_entry_mark_archived,
    ouroboros_entry_mark_reviewed,
    ouroboros_wrapup_list,
)
from yoke_cli.commands.adapters.config import (
    config_example,
    status,
)
from yoke_cli.commands.adapters.dev import dev_db_admin_setup, dev_path_snapshot_prewarm, dev_setup
from yoke_cli.commands.adapters.onboard import (
    onboard,
)
from yoke_cli.commands.adapters.onboard_checklist import (
    onboard_checklist_cmd,
    onboard_checklist_init,
)
from yoke_cli.commands.adapters.project_onboard import (
    onboard_project,
    project_create,
    project_import,
)
from yoke_cli.commands.adapters.config_write import (
    auth_set,
    connection_set,
    env_use,
    project_register,
)
from yoke_cli.commands.adapters.install import (
    project_install,
    project_refresh,
    project_uninstall,
)
from yoke_cli.commands.adapters.project_snapshot import project_snapshot_sync
from yoke_cli.commands.adapters.templates import (
    templates_fetch,
    templates_list,
)
from yoke_cli.commands.adapters.sessions import (
    charge_schedule,
    sessions_checkpoint,
    sessions_checkpoint_read,
    sessions_offer,
    sessions_ownership_guard,
    sessions_touch,
)
from yoke_cli.commands.adapters.usage import ADAPTER_USAGE

__all__ = [
    "items_create", "items_get", "items_list", "items_search", "items_progress_log_append",
    "items_structured_field_replace", "items_scalar_update",
    "items_github_sync", "items_section_upsert", "items_section_get", "items_section_delete",
    "items_structured_field_append_addendum",
    "items_structured_field_section_upsert",
    "items_structured_field_section_append",
    "claims_work_acquire", "claims_work_release", "claims_path_register",
    "claims_path_widen", "claims_path_list", "claims_path_get",
    "claims_path_coordination_decision_build",
    "claims_path_activation_run", "claims_path_required_gate",
    "readiness_check", "readiness_repair_claim_coverage",
    "readiness_repair_stale_count",
    "claims_work_holder_get",
    "claims_work_holder_list", "claims_work_current",
    "path_claims_conflicts_list", "db_claim_amend", "db_read",
    "agents_render", "agents_render_check",
    "packets_render", "packets_check", "board_rebuild", "board_data_get",
    "epic_task_body_replace", "epic_task_split", "epic_task_reassign",
    "epic_task_add", "epic_task_remove", "epic_task_metadata_update",
    "epic_task_review_seed", "epic_task_review_insert",
    "epic_task_review_get", "epic_task_review_list",
    "epic_task_body_get", "epic_task_update_status",
    "epic_task_simulation_upsert", "epic_task_submission_receipt_get",
    "epic_progress_note_append", "epic_progress_note_list",
    "epic_tasks_list",
    "qa_requirement_update", "qa_requirement_auto_create_for_item",
    "qa_run_record_verdict", "qa_browser_context_get", "qa_run_add",
    "qa_run_complete", "qa_artifact_add", "qa_artifact_presign",
    "qa_screenshot_evidence_pending_count", "qa_screenshot_evidence_satisfy",
    "qa_requirement_list", "qa_requirement_get", "qa_requirement_add",
    "qa_requirement_add_batch", "qa_run_list", "qa_run_get",
    "qa_gate_summary",
    "deployment_flows_get", "deployment_flows_stages",
    "deployment_runs_get", "deployment_runs_list",
    "deployment_runs_update", "deployment_runs_resolve_target_env",
    "ephemeral_env_update",
    "doctor_run", "projects_get", "projects_list",
    "projects_resolve_by_github_repo", "projects_create", "projects_update",
    "projects_capability_has", "projects_capability_secret_set",
    "projects_checkout_context", "organizations_get",
    "identity_invite_create", "identity_invite_list",
    "identity_invite_revoke", "identity_link_set", "identity_autojoin_set",
    "project_structure_patch_apply",
    "project_structure_command_definitions_get",
    "project_structure_command_definitions_list",
    "project_structure_deploy_defaults_get",
    "events_emit", "events_query", "events_tail", "events_count",
    "events_anomalies",
    "shepherd_dependency_list", "shepherd_dependency_add",
    "shepherd_dependency_update", "shepherd_dependency_remove",
    "lifecycle_transition", "lifecycle_skip_record_recoverable_substrate",
    "ouroboros_field_note_append",
    "ouroboros_field_note_list", "ouroboros_field_note_get",
    "ouroboros_entry_list", "ouroboros_entry_get",
    "ouroboros_entry_insert", "ouroboros_entry_mark_reviewed",
    "ouroboros_entry_mark_archived", "ouroboros_wrapup_list",
    "github_actions_check_ci", "github_actions_secret_set",
    "github_actions_variable_get", "github_actions_variable_set",
    "strategy_doc_list", "strategy_doc_get", "strategy_doc_create",
    "strategy_doc_replace", "strategy_doc_archive", "strategy_doc_unarchive",
    "strategy_render", "strategy_ingest",
    "strategy_seed_defaults",
    "strategy_carry_register_new", "strategy_carry_candidate_set",
    "strategy_carry_summary", "strategy_carry_mark",
    "strategy_checkpoint_record", "strategy_checkpoint_latest",
    "strategy_master_plan_check",
    "github_connect", "github_pr_create", "github_status",
    "hook_evaluate", "scratch_dispatch_inputs",
    "config_example", "status", "dev_setup", "onboard", "onboard_project",
    "onboard_checklist_cmd", "onboard_checklist_init",
    "env_use", "connection_set", "auth_set",
    "project_create", "project_import", "project_register",
    "project_install", "project_refresh", "project_uninstall",
    "project_snapshot_sync",
    "templates_list", "templates_fetch",
    "sessions_touch", "sessions_checkpoint", "sessions_checkpoint_read",
    "sessions_offer", "sessions_ownership_guard", "charge_schedule",
    "ADAPTER_USAGE",
]
