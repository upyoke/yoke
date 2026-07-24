"""Doctor health check registry.

Imports every HC implementation from its sibling ``doctor_hc_*`` sub-module
and assembles the ordered ``HEALTH_CHECKS`` list consumed by the CLI runner
in ``yoke_core.engines.doctor``. Splitting the registry out keeps the CLI
thin and lets new HCs land without bloating the dispatcher.
"""

from __future__ import annotations

from typing import List

# ---------------------------------------------------------------------------
# Re-export shared types and helpers from doctor_report
# ---------------------------------------------------------------------------
from yoke_core.engines.doctor_report import (  # noqa: F401
    CheckResult,
    DoctorArgs,
    RecordCollector,
    _column_exists,
    _iso_to_epoch,
    _now_epoch,
    _resolve_main_root,
    _resolve_repo_root,
    _run,
    _should_run_hc,
    _table_exists,
)

# Re-export HC functions from sub-modules
from yoke_core.engines.doctor_hc_blocked_flag import (hc_blocked_flag_consistency, hc_blocked_status_drift)  # noqa: F401
from yoke_core.engines.doctor_hc_branch_protection import hc_branch_protection_required_check  # noqa: F401
from yoke_core.engines.doctor_hc_projects_ci import hc_projects_ci_workflow_configured  # noqa: F401
from yoke_core.engines.doctor_hc_project_verification import hc_project_verification_configured  # noqa: F401,E501
from yoke_core.engines.doctor_hc_gate_liveness import hc_gate_liveness  # noqa: F401
from yoke_core.engines.doctor_hc_event_outcome_drift import hc_event_outcome_drift  # noqa: F401
from yoke_core.engines.doctor_hc_event_severity_drift import hc_event_severity_drift  # noqa: F401,E501
from yoke_core.engines.doctor_hc_meta import (  # noqa: F401
    hc_backlog_hygiene,
    hc_backlog_quality,
    hc_blocked_items,
    hc_deferred_items,
    hc_dispatch_chain,
    hc_epic_validation,
    hc_frontmatter_schema,
    hc_lifecycle_continuity,
    hc_orphaned_done_items,
    hc_shepherd_lifecycle,
    hc_status_consistency,
    hc_title_length,
    hc_undeployed_done,
)
from yoke_core.engines.doctor_hc_meta_backlog import hc_incomplete_idea_bodies  # noqa: F401
from yoke_core.engines.doctor_hc_meta_epic import (  # noqa: F401
    hc_missing_flow,
    hc_orphaned_active_items,
    hc_premature_done,
    hc_reviewed_implementation_epics_no_sim,
    hc_shepherd_spec_integrity,
    hc_stale_body,
)
from yoke_core.engines.doctor_hc_meta_epic_tasks import (  # noqa: F401
    hc_empty_task_worktree,
    hc_epic_task_worktree,
    hc_epic_task_worktree_backfill,
    hc_orphan_epic_tasks,
)
from yoke_core.engines.doctor_hc_meta_epic_drift import (  # noqa: F401
    hc_api_vocabulary_drift,
    hc_approval_contract_drift,
    hc_cancelled_blocker_dependencies,
    hc_dependency_drift,
    hc_null_project_items,
    hc_projects_config_alignment,
)

from yoke_core.engines.doctor_hc_db import (  # noqa: F401
    hc_deploy_stage_integrity,
    hc_flow_stage_json,
    hc_flow_workflow_exists,
    hc_incomplete_deploy_stage,
    hc_invalid_item_flows,
    hc_orphan_fk,
    hc_orphaned_ephemeral,
    hc_orphaned_runs,
    hc_preview_occupancy_stale,
    hc_project_flow_migration_apply_coverage,
    hc_run_item_status_consistency,
    hc_run_qa_unsatisfied,
    hc_smoke_artifact_orphan,
    hc_smoke_failure_stale,
    hc_stale_runs,
    hc_validation_no_qa_reqs,
    hc_zombie_ephemeral_envs,
)
from yoke_core.engines.doctor_hc_db_project import (  # noqa: F401
    hc_duplicate_projects,
    hc_migration_audit,
    hc_orphaned_project_items,
    hc_project_fk_integrity,
    hc_project_json_validity,
    hc_project_checkout_mapping,
    hc_projects_without_flows,
    hc_schema_drift,
    hc_schema_script_sync,
)
from yoke_core.engines.doctor_hc_db_events import (  # noqa: F401
    hc_event_emission_rate,
    hc_event_registry_coverage,
    hc_events_destructive_maintenance_audit,
    hc_events_historical_coverage_collapse,
    hc_events_synthetic_contamination,
    hc_stray_db,
)
from yoke_core.engines.doctor_hc_skip_bypass import (  # noqa: F401
    hc_skip_polish_manual_hop,
)
from yoke_core.engines.doctor_hc_atlas import hc_atlas_integrity  # noqa: F401
from yoke_core.engines.doctor_hc_strategy_render_staleness import hc_strategy_render_staleness  # noqa: F401,E501
from yoke_core.engines.doctor_hc_path_claim_rejections import hc_path_claim_register_rejected_with_deps  # noqa: F401,E501
from yoke_core.engines.doctor_hc_path_claim_coordination import hc_path_claim_coordination_rationale  # noqa: F401,E501
from yoke_core.engines.doctor_hc_path_claim_symlink_coverage import hc_path_claim_symlink_coverage  # noqa: F401,E501
from yoke_core.engines.doctor_hc_oneshot_migration import (  # noqa: F401
    hc_oneshot_migration_coverage,
)
from yoke_core.engines.doctor_hc_path_integrity import hc_path_integrity  # noqa: F401
from yoke_core.engines.doctor_hc_qa_runs import hc_qa_runs_mutated  # noqa: F401
from yoke_core.engines.doctor_hc_terminal_recipe_residue import hc_terminal_recipe_residue  # noqa: F401,E501
from yoke_core.engines.doctor_hc_substrate_project_leak import hc_substrate_project_leak  # noqa: F401,E501
from yoke_core.engines.doctor_hc_stranded_migrations import hc_stranded_migration_module  # noqa: F401
from yoke_core.engines.doctor_hc_stop_hook_chain import hc_stop_hook_chain_end_deferred  # noqa: F401
from yoke_core.engines.doctor_hc_retired_schema import (  # noqa: F401
    hc_retired_schema_resurrection,
)
from yoke_core.engines.doctor_hc_db_catalog import (  # noqa: F401
    hc_event_callsite_registry_sync,
    hc_event_catalog_drift,
    hc_synthetic_event_contamination,
)

from yoke_core.engines.doctor_hc_filesystem import (  # noqa: F401
    hc_config_validation, hc_orphaned_temp_files, hc_path_confabulation,
    hc_size_bloat, hc_test_command_validity,
)
from yoke_core.engines.doctor_hc_filesystem_drift import (  # noqa: F401
    hc_arch_consistency, hc_stray_project_files,
)
from yoke_core.engines.doctor_hc_file_size import hc_file_line_limit  # noqa: F401
from yoke_core.engines.doctor_hc_agents import (  # noqa: F401
    hc_agent_consistency,
    hc_agent_canonical_drift,
    hc_browser_substrate,
    hc_hook_executability,
    hc_prompt_command_consistency,
    hc_prompt_doctrine_consistency,
    hc_self_test,
    hc_session_startup_hook,
    hc_stale_session_reclaimer_alive,
    hc_stale_sessions,
)

from yoke_core.engines.doctor_hc_docs import (  # noqa: F401
    hc_claudemd_drift,
    hc_doc_drift,
    hc_doc_health,
)
from yoke_core.engines.doctor_hc_obsoleted_terms import (  # noqa: F401
    hc_obsoleted_terms,
)
from yoke_core.engines.doctor_hc_historical_yok_n import (  # noqa: F401
    hc_historical_yok_n_cruft,
)
from yoke_core.engines.doctor_hc_worktrees import (  # noqa: F401
    _DELEGATED_SYNC_HCS,
    _github_auth_configured,
    hc_branch_divergence,
    hc_cross_project_commits,
    hc_main_checkout,
    hc_orphaned_stashes,
    hc_stale_remote_branches,
    hc_uncaptured_discoveries,
    hc_worktree_health,
)
from yoke_core.engines.doctor_hc_worktrees_gh import (  # noqa: F401
    hc_delegated_sync,
    hc_gh_orphan_detection,
    hc_orphaned_gh_issues,
    hc_project_deploy_flows,
    hc_project_gh_secrets,
    hc_project_gh_auth,
    hc_project_health,
    hc_project_lookup,
    hc_project_repo_exists,
    hc_project_vps_reachable,
    hc_project_worktrees,
    hc_wrong_repo_issues,
)

# HC framework + registry assembly (sibling slice bundles spliced below).
from yoke_core.engines.doctor_registry_types import HealthCheck  # noqa: F401,E402
from yoke_core.engines.doctor_registry_harness import HARNESS_HEALTH_CHECKS  # noqa: E402
from yoke_core.engines.doctor_registry_coordination import COORDINATION_HEALTH_CHECKS  # noqa: E402
from yoke_core.engines.doctor_registry_architecture import ARCHITECTURE_HEALTH_CHECKS  # noqa: E402
from yoke_core.engines.doctor_registry_tier_discipline import TIER_DISCIPLINE_HEALTH_CHECKS  # noqa: E402,E501
from yoke_core.engines.doctor_registry_content_quality import CONTENT_QUALITY_HEALTH_CHECKS  # noqa: E402,E501
HEALTH_CHECKS: List[HealthCheck] = [
    # DB-only: backlog / lifecycle
    HealthCheck("status-consistency", "Backlog status consistency", hc_status_consistency),
    HealthCheck("blocked-items", "Blocked items", hc_blocked_items),
    HealthCheck("blocked-status-drift", "Blocked status drift", hc_blocked_status_drift),
    HealthCheck("blocked-flag-consistency", "Blocked flag consistency", hc_blocked_flag_consistency),
    HealthCheck("dispatch-chain", "Dispatch chain integrity", hc_dispatch_chain),
    HealthCheck("backlog-hygiene", "Backlog hygiene", hc_backlog_hygiene),
    HealthCheck("frontmatter-schema", "Backlog frontmatter schema", hc_frontmatter_schema),
    HealthCheck("title-length", "Title length enforcement", hc_title_length),
    HealthCheck("backlog-quality", "Backlog quality", hc_backlog_quality),
    HealthCheck("incomplete-idea-bodies", "Incomplete idea bodies after stale-heartbeat reclaim", hc_incomplete_idea_bodies),
    HealthCheck("epic-validation", "Per-epic validation", hc_epic_validation),
    HealthCheck("undeployed-done", "Undeployed done items", hc_undeployed_done),
    HealthCheck("orphan-fk", "Orphaned FK references", hc_orphan_fk),
    HealthCheck("orphaned-done-items", "Done items with signs of bypassed ceremony", hc_orphaned_done_items),
    HealthCheck("deferred-items", "Deferred items enforcement (done epics)", hc_deferred_items),
    HealthCheck("shepherd-lifecycle", "Shepherd lifecycle enforcement", hc_shepherd_lifecycle),
    HealthCheck("lifecycle-continuity", "Lifecycle event continuity", hc_lifecycle_continuity),
    HealthCheck("orphaned-active-items", "Orphaned active items", hc_orphaned_active_items),
    HealthCheck("premature-done", "Done items without merged_at", hc_premature_done),
    HealthCheck("shepherd-spec-integrity", "Shepherd spec body integrity", hc_shepherd_spec_integrity),
    HealthCheck("stale-body", "Stale body", hc_stale_body),
    HealthCheck("reviewed-implementation-epics-no-sim", "Reviewed-implementation epics without simulation", hc_reviewed_implementation_epics_no_sim),
    # DB-only: deployment / runs
    HealthCheck("orphaned-runs", "Deployment runs with no member items", hc_orphaned_runs),
    HealthCheck("stale-runs", "Deployment runs stuck at executing", hc_stale_runs),
    HealthCheck("run-item-status-consistency", "Item/run status consistency", hc_run_item_status_consistency),
    HealthCheck("run-qa-unsatisfied", "Succeeded runs with pending blocking QA", hc_run_qa_unsatisfied),
    HealthCheck("preview-occupancy-stale", "Preview environments claimed by inactive runs", hc_preview_occupancy_stale),
    HealthCheck("validation-no-qa-reqs", "Items in reviewing-implementation without QA requirements", hc_validation_no_qa_reqs),
    HealthCheck("smoke-failure-stale", "Stale smoke QA requirements", hc_smoke_failure_stale),
    HealthCheck("smoke-artifact-orphan", "Orphaned QA artifacts", hc_smoke_artifact_orphan),
    HealthCheck("deploy-stage-integrity", "deploy_stage without deployment evidence", hc_deploy_stage_integrity),
    HealthCheck("incomplete-deploy-stage", "Done items with incomplete deploy_stage", hc_incomplete_deploy_stage),
    HealthCheck("flow-stage-json", "Deployment flow stage JSON validity", hc_flow_stage_json),
    HealthCheck("flow-workflow-exists", "Flow stage workflow files exist", hc_flow_workflow_exists),
    HealthCheck("invalid-item-flows", "Items referencing non-existent or cross-project deployment flows", hc_invalid_item_flows),
    HealthCheck("project-flow-migration-apply-coverage", "Declared migration models are reachable via a flow stage", hc_project_flow_migration_apply_coverage),
    HealthCheck("missing-flow", "Items without deployment flow", hc_missing_flow),
    HealthCheck("orphaned-ephemeral", "Orphaned ephemeral environments", hc_orphaned_ephemeral),
    HealthCheck("zombie-ephemeral-envs", "Zombie ephemeral environments", hc_zombie_ephemeral_envs),
    # DB-only: project integrity
    HealthCheck("project-fk-integrity", "Project FK integrity", hc_project_fk_integrity),
    HealthCheck("project-checkout-mapping", "Project checkout mappings", hc_project_checkout_mapping),
    HealthCheck("project-json-validity", "Project JSON field validity", hc_project_json_validity),
    HealthCheck("projects-without-flows", "Projects without deployment flows", hc_projects_without_flows),
    HealthCheck("duplicate-projects", "Duplicate project IDs / prefixes", hc_duplicate_projects),
    HealthCheck("orphaned-project-items", "Orphaned project references in items", hc_orphaned_project_items),
    HealthCheck("null-project-items", "NULL project items", hc_null_project_items),
    HealthCheck("projects-config-alignment", "Projects config alignment", hc_projects_config_alignment),
    HealthCheck("dependency-drift", "Dependency drift detection", hc_dependency_drift),
    HealthCheck("cancelled-blocker-dependencies", "Cancelled blocker dependencies", hc_cancelled_blocker_dependencies),
    # DB-only: epic task / worktree
    HealthCheck("epic-task-worktree", "Epic task worktree backfill", hc_epic_task_worktree),
    HealthCheck("empty-task-worktree", "Epic tasks with empty worktree fields", hc_empty_task_worktree),
    HealthCheck("orphan-epic-tasks", "Orphan epic tasks", hc_orphan_epic_tasks),
    HealthCheck("epic-task-worktree-backfill", "Epic tasks with empty worktree fields", hc_epic_task_worktree_backfill),
    # DB-only: schema / integrity
    HealthCheck("schema-drift", "Schema drift detection", hc_schema_drift),
    HealthCheck("schema-script-sync", "Script-schema column contract", hc_schema_script_sync),
    HealthCheck("migration-audit", "Migration audit evidence", hc_migration_audit),
    # DB-only: events
    HealthCheck("event-registry-coverage", "Event registry coverage", hc_event_registry_coverage),
    HealthCheck("event-emission-rate", "Event emission rate", hc_event_emission_rate),
    HealthCheck("synthetic-event-contamination", "Synthetic event contamination", hc_synthetic_event_contamination),
    HealthCheck("event-callsite-registry-sync", "Event call site registry sync", hc_event_callsite_registry_sync),
    HealthCheck("event-catalog-drift", "Event catalog drift", hc_event_catalog_drift),
    # events ledger trust signals
    HealthCheck("events-synthetic-contamination", "Synthetic or test rows in canonical events ledger", hc_events_synthetic_contamination),
    HealthCheck("events-historical-coverage-collapse", "Historical delivery/status telemetry coverage", hc_events_historical_coverage_collapse),
    HealthCheck("events-destructive-maintenance-audit", "Destructive maintenance audit evidence", hc_events_destructive_maintenance_audit),
    HealthCheck("event-outcome-drift", "Historical event-outcome drift", hc_event_outcome_drift),
    HealthCheck("event-severity-drift", "Historical event-severity drift", hc_event_severity_drift),
    HealthCheck("skip-polish-manual-hop", "Manual polish-skip bookkeeping hops that should use --skip-polish", hc_skip_polish_manual_hop),
    HealthCheck("atlas-integrity", "Atlas integrity", hc_atlas_integrity),
    HealthCheck("strategy-render-staleness", "Rendered .yoke/strategy/ views stale vs strategy_docs DB rows", hc_strategy_render_staleness),
    HealthCheck("path-claim-register-rejected-with-deps", "PathClaimRegistrationBlocked rejections where dep-graph names the upstream", hc_path_claim_register_rejected_with_deps),
    HealthCheck("path-claim-coordination-rationale", "Coordination_only attestation rationale stale or empty", hc_path_claim_coordination_rationale),
    HealthCheck("path-claim-symlink-coverage", "Non-terminal claim covers a symlink without its canonical target", hc_path_claim_symlink_coverage),
    HealthCheck("oneshot-migration-coverage", "Governed DB-mutation authoring coverage", hc_oneshot_migration_coverage),
    HealthCheck("stranded-migration-module", "Completed migration module(s) still present", hc_stranded_migration_module),
    HealthCheck("stop-hook-chain-end-deferred", "Stop-hook deferred chains aged past stale window", hc_stop_hook_chain_end_deferred),
    HealthCheck("retired-schema-resurrection", "Retired schema surfaces present on authoritative DB", hc_retired_schema_resurrection),
    HealthCheck("qa-runs-mutated", "qa_runs rows whose raw_result mixes failing verdict with resolution narrative", hc_qa_runs_mutated),
    # Git / filesystem HCs
    HealthCheck("main-checkout", "Main repo branch checkout", hc_main_checkout),
    HealthCheck("worktree-health", "Worktree health", hc_worktree_health),
    HealthCheck("branch-divergence", "Local/remote branch divergence", hc_branch_divergence),
    HealthCheck("uncaptured-discoveries", "Uncaptured discoveries", hc_uncaptured_discoveries),
    HealthCheck("orphaned-stashes", "Orphaned pre-merge stashes", hc_orphaned_stashes),
    HealthCheck("cross-project-commits", "Cross-project commit contamination", hc_cross_project_commits),
    HealthCheck("path-confabulation", "Path confabulation", hc_path_confabulation),
    HealthCheck("orphaned-temp-files", "Orphaned temp files", hc_orphaned_temp_files),
    HealthCheck("stray-db", "Stray yoke.db at repo root", hc_stray_db),
    # Doc / quality / meta-consistency
    HealthCheck("doc-drift", "Documentation drift", hc_doc_drift),
    HealthCheck("doc-health", "Documentation health audit", hc_doc_health),
    HealthCheck("obsoleted-terms", "Obsoleted terms in live files", hc_obsoleted_terms),
    HealthCheck("historical-yok-n-cruft", "Historical YOK-N references in live prose", hc_historical_yok_n_cruft),
    HealthCheck("terminal-recipe-residue", "Retired terminal-soup recipes in live guidance", hc_terminal_recipe_residue),
    HealthCheck("substrate-project-leak", "Substrate project filename leak", hc_substrate_project_leak),
    HealthCheck("agent-consistency", "Agent prompt consistency", hc_agent_consistency),
    HealthCheck("hook-executability", "Hook script executability", hc_hook_executability),
    HealthCheck("self-test", "Self-test", hc_self_test),
    HealthCheck("claudemd-drift", "AGENTS.md semantic drift", hc_claudemd_drift),
    HealthCheck("config-validation", "Config file validation", hc_config_validation),
    HealthCheck("arch-consistency", "Architectural consistency audit", hc_arch_consistency),
    HealthCheck("agent-canonical-drift", "Claude adapter canonical drift", hc_agent_canonical_drift),
    HealthCheck("size-bloat", "Size/bloat monitor", hc_size_bloat),
    HealthCheck("file-line-limit", "Authored file 350-line limit", hc_file_line_limit),
    HealthCheck("prompt-command-consistency", "Prompt/docs advertise supported CLI syntax", hc_prompt_command_consistency),
    HealthCheck("prompt-doctrine-consistency", "Canonical giant doctrine + short-form consistency", hc_prompt_doctrine_consistency),
    HealthCheck("stray-project-files", "Stray project output directories", hc_stray_project_files),
    HealthCheck("api-vocabulary-drift", "API vocabulary drift", hc_api_vocabulary_drift),
    HealthCheck("approval-contract-drift", "Approval contract drift", hc_approval_contract_drift),
    HealthCheck("test-command-validity", "Test command validity", hc_test_command_validity),
    HealthCheck("path-integrity", "Path-integrity verifier surface (shadow-mode)", hc_path_integrity),
    # Project-specific HCs (non-yoke)
    HealthCheck("project-lookup", "Project lookup", hc_project_lookup),
    HealthCheck("project-repo-exists", "Project repo exists", hc_project_repo_exists),
    HealthCheck("project-gh-auth", "GitHub App auth", hc_project_gh_auth),
    HealthCheck("project-worktrees", "Project worktree health", hc_project_worktrees),
    HealthCheck("project-deploy-flows", "Deployment flow state", hc_project_deploy_flows),
    HealthCheck("project-health", "Production health", hc_project_health, github_dependent=True),
    HealthCheck("project-gh-secrets", "GitHub Actions secrets", hc_project_gh_secrets, github_dependent=True),
    HealthCheck("project-vps-reachable", "VPS reachable", hc_project_vps_reachable, github_dependent=True),
    HealthCheck("stale-remote-branches", "Stale remote branches", hc_stale_remote_branches, github_dependent=True),
    HealthCheck("orphaned-gh-issues", "Orphaned GitHub issues", hc_orphaned_gh_issues, github_dependent=True),
    HealthCheck("gh-orphan-detection", "GitHub orphan detection", hc_gh_orphan_detection, github_dependent=True),
    HealthCheck("wrong-repo-issues", "Wrong-repo GitHub issues", hc_wrong_repo_issues, github_dependent=True),
    HealthCheck("branch-protection-required-check", "Branch protection required check", hc_branch_protection_required_check, github_dependent=True),
    HealthCheck("projects-ci-workflow-configured", "Per-project CI workflow capability", hc_projects_ci_workflow_configured),
    HealthCheck("project-verification-configured", "Project has a test command or merge policy", hc_project_verification_configured),  # noqa: E501
    HealthCheck("gate-liveness", "Pre-commit gate is the live Yoke shim", hc_gate_liveness),  # noqa: E501
    HealthCheck("delegated-sync", "Delegated sync HCs", hc_delegated_sync, github_dependent=True),
]

# Preserve the long-standing invariant that the harness/session bundle stays
# at the tail; coordination + architecture checks splice immediately before it.
HEALTH_CHECKS.extend(COORDINATION_HEALTH_CHECKS + ARCHITECTURE_HEALTH_CHECKS + TIER_DISCIPLINE_HEALTH_CHECKS + CONTENT_QUALITY_HEALTH_CHECKS + HARNESS_HEALTH_CHECKS)  # noqa: E501
