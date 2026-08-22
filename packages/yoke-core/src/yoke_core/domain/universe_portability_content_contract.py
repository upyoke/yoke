"""Portable archive schema compatibility and user-content contract."""

from __future__ import annotations

ARCHIVE_OMITTABLE_TARGET_TABLES = frozenset(
    {
        "addressed_event_deliveries",
        "capability_secrets",
        "decision_request_actor_authorities",
        "decision_request_role_authorities",
        "decision_requests",
        "item_strategy_docs",
        "migration_content_adoptions",
        "ouroboros_entry_dispositions",
        "qa_methods",
        "qa_plan_cases",
        "qa_plan_item_attachments",
        "qa_plan_project_defaults",
        "qa_plans",
        "session_launch_attempts",
        "session_message_attempts",
        "session_message_recipients",
        "session_relays",
        "strategy_doc_claims",
        "strategy_doc_revisions",
        "test_machine_verifications",
    }
)

ARCHIVE_OMITTABLE_TARGET_SEQUENCES = frozenset(
    {
        "capability_secrets_id_seq",
        "strategy_doc_revisions_id_seq",
    }
)
ARCHIVE_FORBIDDEN_TABLE_DATA = frozenset({"capability_secrets"})
ARCHIVE_FORBIDDEN_SEQUENCE_DATA = frozenset({"capability_secrets_id_seq"})
ARCHIVE_OMITTABLE_TARGET_COLUMNS = {
    "applied_migrations": frozenset({"content_sha256"}),
    "addressed_event_deliveries": frozenset(
        {
            "event_actor_id",
            "event_actor_label",
            "event_envelope",
            "event_name",
            "event_outcome",
            "project_id",
        }
    ),
    "project_github_repo_bindings": frozenset(
        {
            "last_sync_at",
            "last_sync_error",
            "last_sync_outcome",
        }
    ),
    "qa_requirements": frozenset(
        {
            "baseline_position",
            "case_position",
            "entry_surface",
            "runner_id",
            "expected_outcome",
            "host_baseline",
            "instructions",
            "method_config",
            "method_id",
            "method_name",
            "plan_case_key",
            "plan_id",
            "required_completion",
            "verdict_path",
            "workflow_transition_id",
        }
    ),
    "qa_runs": frozenset({"capture_degraded_reason", "case_outcome"}),
    "strategy_doc_revisions": frozenset({"session_id"}),
    "strategy_docs": frozenset({"parent_slug"}),
}
ARCHIVE_COLUMN_RENAMES = {
    ("harness_sessions", "executor_display_name"): "executor_surface",
    ("organizations", "auto_join_domain"): "domain",
    ("qa_artifacts", "storage_path"): "artifact_handle",
}

USER_CONTENT_TABLES: tuple[str, ...] = (
    "actor_invites",
    "actor_project_roles",
    "api_token_audit",
    "api_tokens",
    "capability_secrets",
    "caveat_dispositions",
    "coordination_leases",
    "deployment_run_items",
    "deployment_run_qa",
    "projects",
    "items",
    "item_activity_days",
    "project_code_days",
    "item_dependencies",
    "item_sections",
    "item_status_transitions",
    "epic_dispatch_chains",
    "epic_progress_notes",
    "epic_task_files",
    "epic_tasks",
    "release_entries",
    "qa_artifacts",
    "qa_requirements",
    "qa_runs",
    "strategy_docs",
    "strategy_doc_revisions",
    "strategy_checkpoints",
    "strategize_landed_carry",
    "deployment_runs",
    "ephemeral_environments",
    "environments",
    "events",
    "function_call_ledger",
    "github_app_installations",
    "github_workflow_dispatch_intents",
    "harness_sessions",
    "merge_locks",
    "ouroboros_entries",
    "path_claim_amendments",
    "path_claim_overrides",
    "path_claim_task_bindings",
    "path_claim_targets",
    "path_claims",
    "path_context_values",
    "path_integrity_failures",
    "path_integrity_fixtures",
    "path_integrity_repairs",
    "path_integrity_runs",
    "path_moves",
    "path_snapshot_entries",
    "path_snapshot_symlink_facts",
    "path_snapshot_sync_upload_chunks",
    "path_snapshot_sync_uploads",
    "path_snapshots",
    "path_targets",
    "project_capabilities",
    "project_github_repo_bindings",
    "project_onboarding_checklist_rows",
    "project_onboarding_runs",
    "session_tool_calls",
    "session_messages",
    "session_launches",
    "shepherd_verdicts",
    "sites",
    "web_sessions",
    "work_claims",
    "qa_methods",
    "qa_plan_cases",
    "qa_plan_item_attachments",
    "qa_plan_project_defaults",
    "qa_plans",
    "item_strategy_docs",
    "strategy_doc_claims",
    "decision_requests",
    "decision_request_actor_authorities",
    "decision_request_role_authorities",
    "addressed_event_deliveries",
    "ouroboros_entry_dispositions",
    "test_machine_verifications",
)

USER_CONTENT_COUNT_SQL = {
    "actor_invites": (
        "SELECT COUNT(*) FILTER (WHERE status <> 'accepted') + "
        "GREATEST(COUNT(*) FILTER (WHERE status = 'accepted') - 1, 0) "
        "FROM actor_invites"
    ),
    # Built-in and Pack methods are executable product configuration. Only
    # project-authored methods make a freshly initialized universe non-empty.
    "qa_methods": "SELECT COUNT(*) FROM qa_methods WHERE source_kind = 'project'",
}

__all__ = [
    "ARCHIVE_COLUMN_RENAMES",
    "ARCHIVE_FORBIDDEN_SEQUENCE_DATA",
    "ARCHIVE_FORBIDDEN_TABLE_DATA",
    "ARCHIVE_OMITTABLE_TARGET_COLUMNS",
    "ARCHIVE_OMITTABLE_TARGET_SEQUENCES",
    "ARCHIVE_OMITTABLE_TARGET_TABLES",
    "USER_CONTENT_COUNT_SQL",
    "USER_CONTENT_TABLES",
]
