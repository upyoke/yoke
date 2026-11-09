"""Portable archive schema compatibility and user-content contract."""

from __future__ import annotations

# Secrets are intentionally excluded from portable archives.
ARCHIVE_OMITTABLE_TARGET_TABLES = frozenset({"capability_secrets"})
ARCHIVE_OMITTABLE_TARGET_SEQUENCES = frozenset({"capability_secrets_id_seq"})
ARCHIVE_FORBIDDEN_TABLE_DATA = frozenset({"capability_secrets"})
ARCHIVE_FORBIDDEN_SEQUENCE_DATA = frozenset({"capability_secrets_id_seq"})
USER_CONTENT_TABLES: tuple[str, ...] = (
    "actor_invites",
    "actor_message_recipients",
    "actor_project_roles",
    "api_token_audit",
    "api_tokens",
    "capability_secrets",
    "caveat_dispositions",
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
    "audiences",
    "audience_rules",
    "decision_requests",
    "inbox_posts",
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
    "ARCHIVE_FORBIDDEN_SEQUENCE_DATA",
    "ARCHIVE_FORBIDDEN_TABLE_DATA",
    "ARCHIVE_OMITTABLE_TARGET_SEQUENCES",
    "ARCHIVE_OMITTABLE_TARGET_TABLES",
    "USER_CONTENT_COUNT_SQL",
    "USER_CONTENT_TABLES",
]
