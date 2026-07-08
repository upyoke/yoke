"""Authoritative event-registry data tuples.

Sibling of :mod:`yoke_core.domain.populate_registry`. Holds the
operator-authored data tables that drive the deprecate, retire, and
authoritative-metadata layers of the populator pipeline:

- :data:`DEPRECATE_LIST`: events to mark ``deprecated`` because they have
  zero active call sites (and, where verified, zero historical rows).
- :data:`RETIRE_LIST`: events to mark ``retired`` because they were
  renamed to a newer name; historical rows remain in the events ledger
  under the old name but no new ones are written.
- :data:`EXPECTED_LOW_CADENCE_ACTIVE`: active events that are intentionally
  absent for more than 30 days because they represent rare failures,
  operator overrides, or recovery paths.
- :data:`AUTHORITATIVE_METADATA`: the final metadata layer applied via
  ``ensure_registry_entry`` (idempotent insert then UPDATE).  This layer
  overrides both discovery-inferred and earlier curated values.

Note: ``AUTHORITATIVE_METADATA`` is ordered as ``(name, kind, event_type,
service, severity, description)``; other tuple families differ, so do not
reorder rows during edits.
"""

from __future__ import annotations
from typing import Tuple
# Events marked ``deprecated``: zero active call sites and (where
# verified) zero historical rows.
DEPRECATE_LIST: Tuple[str, ...] = (
    # Browser substrate events (future-use registrations)
    "BrowserDaemonStarted",
    "BrowserDaemonStopped",
    "BrowserDiffCompleted",
    "BrowserSnapshotCaptured",
    "BrowserStepExecuted",
    # Deployment CRUD events (never emitted)
    "DeploymentRunCancelled",
    "DeploymentRunCreated",
    "DeploymentRunItemAdded",
    "DeploymentRunItemRemoved",
    # Browser baseline events declared in curated metadata but never wired
    # to an emitter — no live call sites and no successor name. Mark
    # deprecated so the stale-active doctor check stops flagging them.
    "BaselinePromoted",
    "BaselineRecorded",
    # /yoke charge dispatch-decision event declared in authoritative
    # metadata but never wired to an emitter; the charge skill records
    # decisions through ChargeFrontierObserved / FrontierStepSelected
    # instead. No successor name, no live call sites.
    "ChargeDecisionMade",
    # /yoke feed event names declared in both curated and authoritative
    # tables but never emitted by the feed skill. No successor name.
    "FeedCompleted",
    "FeedStarted",
    # QA-artifact event declared in curated metadata but never wired to
    # an emitter; artifact tracking happens inline on the qa_runs row.
    # No successor name, no live call sites.
    "QAArtifactAttached",
    # Discovery contamination: auto-discovery misread the literal
    # severity string "INFO" as an event name.
    "INFO",
)

# Events to mark ``retired`` (not ``deprecated``) — replaced by a newer name.
RETIRE_LIST: Tuple[str, ...] = (
    "ModeChosen",
    # AgentSessionStarted was renamed first to SessionSentFirstUserPromptSubmit,
    # then to HarnessSessionSentFirstUserPromptSubmit, because the old name
    # was misleading — it suggested a session-lifecycle event tied to
    # session creation, but it actually fires from the UserPromptSubmit
    # hook at first prompt. Historical rows remain in the events ledger
    # under the old name; no new ones will be written.
    "AgentSessionStarted",
    # SessionStartPayloadObserved was a one-shot diagnostic used to
    # inspect what fields Claude Code's VS Code extension actually sends
    # in its SessionStart payload. Question answered: VS Code's payload
    # omits the ``model`` field entirely, so the emitter has been removed.
    # Historical rows stay in the ledger as provenance; no new ones fire.
    "SessionStartPayloadObserved",
    # Session* -> HarnessSession* rename: the harness_sessions table is
    # the source of truth for these events, and the name prefix now
    # reflects that. Historical rows under the old names stay; no new
    # ones are written.
    "AgentSessionStopped",
    "SessionRegistered",
    "SessionStarted",
    "SessionEnded",
    "SessionHookFailed",
    "SessionOffered",
    "SessionSentFirstUserPromptSubmit",
    "SessionEndRejectedActiveClaim",
    "SessionEndReleasedClaims",
    "StaleSessionReclaimed",
    "StaleSessionSweepCompleted",
    # ToolCall* / LifecycleMutationDetected -> HarnessToolCall* /
    # HarnessLifecycleMutationDetected rename: these fire from Yoke-owned
    # PreToolUse/PostToolUse hook surfaces, so the Harness prefix matches
    # the HarnessSession* convention and makes "emitted from a harness
    # hook" legible at a glance. Historical rows under the old names stay
    # in the ledger; no new ones are written.
    "ToolCallStarted",
    "ToolCallCompleted",
    "ToolCallFailed",
    "ToolCallDenied",
    "ToolCallStructuredExit",
    "LifecycleMutationDetected",
    # WorktreeHandoffEmitted carried parent-session-stop / manual-relaunch
    # semantics. Retired; worktree creation is no longer a session
    # boundary, and the session's authority over the new worktree comes
    # from its work-claim (validated per call by lint_session_cwd).
    # Historical rows stay in the ledger; no new ones fire.
    "WorktreeHandoffEmitted",
    # SessionExecutionScopeChanged carried the session-envelope
    # execution-scope transitions (main <-> worktree). Retired together
    # with the envelope; the per-call claim-based lint authority replaces
    # the envelope. Historical rows stay in the ledger; no new ones fire.
    "SessionExecutionScopeChanged",
    # ClaimReacquiredAfterHandoff registry row was deleted when explicit
    # handoffs replaced same-session reacquire; retire so the rogue
    # check sees a registered row.
    "ClaimReacquiredAfterHandoff",
    # PathContextMigrated emitter (path_context_continuity_cutover.py)
    # was deleted in commit 966d30574 alongside the path-posture doc-link
    # cutover; see docs/archive/decisions/path-posture-doc-links-cutover.md.
    # Historical rows remain in the ledger; no new ones fire.
    "PathContextMigrated",
    # LeakAttempt is a test-isolation fixture name; canonical-DB rows
    # are bounded by the gate. Retire so the rogue check stops flagging.
    "LeakAttempt",
    # BodyRegeneration* paired with body-cache removal — emitters were
    # deleted when body rendering moved to on-demand. Description fields
    # already say RETIRED; flip status to match.
    "BodyRegenerated", "BodyRegenerationFailed",
    # DeploymentEventMigrated was a one-shot historical migration
    # backfill event; emitter deleted, historical rows remain.
    "DeploymentEventMigrated",
)


# Active events that should not trip HC-event-registry-coverage solely because
# they did not emit in the last 30 days. Each remains active because the live
# emitter represents a rare failure, override, recovery, or exceptional path.
EXPECTED_LOW_CADENCE_ACTIVE: Tuple[str, ...] = (
    "BranchProtectionCheckFailed",
    "BoardRebuildCommandFailed",
    "BrowserDaemonStartupFailed",
    "ChainEndDeferred",
    "DataLossDetected",
    "DeploymentRunFailed",
    "DeploymentRunStageFailed",
    "DispatcherDownstreamDegraded",
    "GitHubCloseFailure",
    "HarnessSessionEndDeferred",
    "HarnessSessionResumeBlockShown",
    "HarnessToolCallStructuredExit",
    "HookExecutionFailed",
    "IdeaClaimHeld",
    "IdeaReadinessClaimCoverageRepairApplied",
    "IssueMigrated",
    "ItemClaimReleaseRefused",
    "LeaseAcquired",
    "LeaseHeartbeated",
    "LeaseReleased",
    "MergePullRequestMergeRetried",
    "MergeTargetStale",
    "MergeVerificationFailed",
    "MigrationCompleted",
    "MigrationModuleRetireSkipped",
    "MigrationRolledBack",
    "OperatorLeaseRelease",
    "PathClaimBlockedReasonRefreshed",
    "PathIntegrityFailureDetected",
    "PathIntegrityRepairApplied",
    "PathTargetSymlinkSkipped",
    "PathTargetTentative",
    "PreviewEnvCleaned",
    "PreviewEnvCreated",
    "PreviewEnvOverwritten",
    "RetiredSchemaResurrectionAttempt",
    "SMLRefreshCompleted",
    "SessionCwdBindingFailOpen",
    "SessionCwdBindingHealthCheckFailed",
    "SessionOfferLaneOverrideIgnored",
    "SessionReactivationReacquiredClaims",
    "StrategyDocArchived",
    "StrategyDocUnarchived",
    "YokeFunctionPermissionDenied",
    "WorkHandedOff",
)

# Authoritative metadata layer — see module docstring for ordering and apply contract.
AUTHORITATIVE_METADATA: Tuple[Tuple[str, str, str, str, str, str], ...] = (
    ("AdapterDispatchChosen", "workflow", "adapter_dispatch", "cli", "INFO", "Emitted when a downstream adapter path is chosen for charge/resume"),
    ("AdvancePhaseCompleted", "workflow", "advance_phase", "yoke_core.engines.advance_implementation_entry", "INFO", "Emitted per phase by the /yoke advance implementation-entry orchestrator. Carries phase (preflight|worktree|environment|finalize), outcome (completed|skipped:<reason>|blocked:<reason>), duration_ms, and phase-specific context. The full phase trail proves the implementation-entry composition committed end-to-end inside one Python process."),
    ("BrowserDaemonStartupFailed", "system", "browser_daemon", "browser_qa", "ERROR", "Browser daemon failed to start after bounded recovery attempts during browser QA"),
    ("BodyRegenerated", "lifecycle", "body_render", "render-body", "INFO", "RETIRED — body cache columns removed; body rendered on demand"),
    ("BodyRegenerationFailed", "lifecycle", "body_render", "render-body", "ERROR", "RETIRED — body cache columns removed; body rendered on demand"),
    ("BoardRebuildCommandCompleted", "workflow", "board_rebuild_command", "yoke_cli.commands.adapters.board", "INFO", "Human `yoke board rebuild` command completed. Carries command, repo_root, board_path, force, scope, output_name, print_mode, started_at, completed_at, duration_ms, status, exit_code, targets, pid, and cwd."),
    ("BoardRebuildCommandFailed", "workflow", "board_rebuild_command", "yoke_cli.commands.adapters.board", "WARN", "Human `yoke board rebuild` command failed or returned a nonzero rebuild outcome. Carries command, repo_root, board_path, force, scope, output_name, print_mode, started_at, completed_at, duration_ms, status, exit_code, targets or exception detail, pid, and cwd."),
    ("BoardRebuildCommandStarted", "workflow", "board_rebuild_command", "yoke_cli.commands.adapters.board", "INFO", "Human `yoke board rebuild` command started before the rebuild lock/render path. Carries command, repo_root, board_path, force, scope, output_name, print_mode, started_at, pid, and cwd; paired with completion/failure by trace_id."),
    ("BranchProtectionCheckFailed", "lifecycle", "branch_protection_drift", "yoke_core.engines.doctor_hc_branch_protection", "WARN", "Emitted by HC-branch-protection-required-check when main-branch protection on the project repo is absent, its required_status_checks.contexts list is missing one or more yoke-ci workflow checks, or branch protection is unavailable due to repo plan/visibility (notify-only mode). Context: repo, branch, expected_checks, actual_contexts, missing_checks, reason (branch_protection_absent|missing_required_checks|branch_protection_unavailable), drift_detected_at."),
    ("ChainBudgetUnused", "workflow", "chain_checkpoint", "backend", "INFO", "Emitted on a /yoke do terminal checkpoint when useful chain budget remained unused (all candidates blocked/stale/disabled/recoverable). Carries session_id, step, max_chain_steps, remaining_budget, terminal_reason, and the candidate filter trail."),
    ("ChainDeclineOverridden", "audit", "chain_checkpoint", "backend", "WARN", "Emitted when session-end is invoked with --override-chain-end and a non-empty --chain-end-rationale, bypassing the structural chain-budget guard. Carries session_id, checkpoint step, max_chain_steps, action, item_id, override_flag, and the operator-supplied rationale."),
    ("ChainEndDeferred", "audit", "chain_checkpoint", "backend", "INFO", "Emitted when session-end-if-empty (Stop hook) declines to end a session because a chainable checkpoint still has budget remaining. Carries session_id, triggered_by, checkpoint step, max_chain_steps, handler_outcome, chainable, action, item_id, and the most recent work_claims.released_at timestamp."),
    ("ChainStepCompleted", "workflow", "chain_checkpoint", "backend", "STATUS", "Emitted after a /yoke do mode handler returns, recording step, action, chainable, handler outcome, and targeted work identity for chain-decision telemetry"),
    ("ChargeDecisionMade", "lifecycle", "charge", "charge-skill", "INFO", "Charge dispatch decision made (dispatched or cancelled)"),
    ("ClaimVerificationBypassed", "lifecycle", "claim_verification", "yoke-core", "INFO", "Claim verification bypassed via audited system or repair path"),
    ("ClaimVerificationDenied", "lifecycle", "claim_verification", "yoke-core", "INFO", "Status mutation denied: current session does not hold the matching work claim"),
    ("DataLossDetected", "system", "db_alarm", "yoke_core.domain.db_error_hook_collapse", "FATAL", "Expected low-cadence fatal alarm emitted when row-count collapse is detected after DDL; retained active because absence usually means the alarm did not need to fire."),
    ("DependencyGateEvaluated", "workflow", "dependency_gate", "cli", "INFO", "Batch summary of dependency gate evaluation from planning kernel"),
    ("DeploymentApprovalGranted", "lifecycle", "deployment_run", "cli", "INFO", "Human approval granted for a deployment pipeline stage"),
    ("DeploymentCoreContainerDeployed", "lifecycle", "deployment_run", "yoke_core.domain.deploy_core_container", "STATUS", "Yoke core container deployed to a target environment and verified healthy through the origin"), ("DeploymentCoreContainerRolledBack", "lifecycle", "deployment_run", "yoke_core.domain.deploy_core_container_rollback", "WARN", "Post-swap health gate failed and the core-deploy executor attempted one bounded rollback to the pre-swap image; outcome completed/failed records whether the prior container reported healthy again. The deploy stage fails either way — rollback restores service, never success. Context: rolled_back_to, failed_image_ref, origin_host, rollback_healthy."),
    ("DeploymentEnvironmentBootstrapped", "lifecycle", "deployment_run", "yoke_core.domain.deploy_environment_bootstrap", "STATUS", "A deploy environment's empty Postgres database was bootstrapped to the complete Yoke control-plane shape (init chain + event-registry population) via the environment-bootstrap executor"),
    ("DeploymentEphemeralDeployed", "lifecycle", "deployment_run", "yoke_core.domain.deploy_ephemeral", "STATUS", "A branch preview environment (core container + disposable Postgres) was deployed on the host env box and passed on-box plus public wildcard health checks"), ("DeploymentEphemeralTorndown", "lifecycle", "deployment_run", "yoke_core.domain.deploy_ephemeral", "STATUS", "A branch preview environment's compose project, volumes, and deploy directory were torn down"),
    ("DeploymentRunExecuting", "lifecycle", "deployment_run", "deployment-runs-db", "STATUS", "Run started executing"), ("DeploymentRunFailed", "lifecycle", "deployment_run", "deployment-runs-db", "STATUS", "Run failed"),
    ("DeploymentRunStageCompleted", "lifecycle", "deployment_run", "deployment-runs-db", "STATUS", "Pipeline stage completed"),
    ("DeploymentRunStageFailed", "lifecycle", "deployment_run", "deployment-runs-db", "STATUS", "Pipeline stage failed"),
    ("DeploymentRunStageStarted", "lifecycle", "deployment_run", "deployment-runs-db", "STATUS", "Pipeline entered a new stage"),
    ("DeploymentRunSucceeded", "lifecycle", "deployment_run", "deployment-runs-db", "STATUS", "Run completed successfully"),
    ("DispatcherDownstreamDegraded", "workflow", "yoke_function_dispatch", "yoke_core.domain.yoke_function_dispatch", "WARN", "Yoke function-call dispatcher detected partial-state failure: the primary mutation committed but a downstream side effect (GitHub sync, board rebuild, follow-on event emission) failed. HTTP 207 surface; the response.warnings array names the failed step and response.success remains true."),
    ("DispatcherIdempotencyReplay", "workflow", "yoke_function_dispatch", "yoke_core.domain.yoke_function_dispatch", "INFO", "Yoke function-call dispatcher returned a cached response because the (function, request_id) pair was previously dispatched. The cached result is returned verbatim; no handler runs. Idempotency-collision (same request_id, different function id) emits a different shape and HTTP 409."),
    ("YokeFunctionCalled", "workflow", "yoke_function_dispatch", "yoke_core.domain.yoke_function_dispatch", "INFO", "Yoke function-call dispatcher invoked a registered handler. Carries function id, request_id, actor_id auth context, target, claim verification outcome, permission key, and downstream surface results."),
    ("YokeFunctionPermissionDenied", "workflow", "yoke_function_dispatch", "yoke_core.domain.yoke_function_dispatch", "WARN", "Yoke function-call dispatcher denied a request before handler execution because the actor lacks the required project permission."),
    ("DbClaimAmended", "workflow", "db_claim_amendment", "yoke_core.domain.db_claim", "INFO", "DB claim amended through the sanctioned unified workflow"),
    ("FeedCompleted", "lifecycle", "feed", "feed-skill", "STATUS", "Feed skill invocation completed (SML materialization or graph refresh)"),
    ("FeedStarted", "lifecycle", "feed", "feed-skill", "STATUS", "Feed skill invocation started (SML materialization or graph refresh)"),
    ("FrontierComputed", "workflow", "frontier_computation", "frontier.py", "STATUS", "Frontier computed by core Python path"),
    ("FrontierStepSelected", "workflow", "scheduler_selection", "cli", "INFO", "Emitted from scheduler after step selection is finalized"),
    ("GitHubCloseFailure", "system", "github_sync", "yoke_core.domain.update_status", "WARN", "GitHub issue close failed (emitted by yoke_core.domain.update_status)"),
    ("IdeaClaimHeld", "lifecycle", "idea_claim_lifecycle", "yoke_core.domain.idea_claim_events", "INFO", "Emitted when /yoke idea releases a draft work claim with reason 'idea-complete'. Carries claim_id, claimed_at, released_at, duration_ms, claim_reason_intent ('draft-in-progress'), and release_reason_intent ('idea-complete'). Observability surface for how long /yoke idea sessions hold a draft claim during body composition; doctor and Ouroboros consume this to detect stalled drafts."),
    ("IdeaReadinessAutofixApplied", "lifecycle", "readiness_repair", "yoke_core.domain.idea_readiness_repair", "INFO", "Refine-entry idea_readiness_check stale-count auto-repair applied. Carries item_id, field (typically 'spec'), repaired_paths (path/recorded/actual), refused_paths, and rerun_verdict ('pass' or 'block')."),
    ("IdeaReadinessClaimCoverageRepairApplied", "lifecycle", "readiness_repair", "yoke_core.domain.idea_readiness_repair_claim_coverage", "INFO", "Refine-entry claim-coverage auto-repair applied: widen for FILE_BUDGET_NOT_IN_CLAIM, narrow for CLAIM_NOT_IN_FILE_BUDGET, or widen_and_narrow when both axes are present (partial-progress flow runs both, aggregates repaired and refused paths). Carries item_id, action ('widen'/'narrow'/'widen_and_narrow'), repaired_paths, refused_paths, and rerun_verdict ('pass' or 'block')."),
    ("IssueMigrated", "system", "github_sync", "yoke_core.engines.doctor", "INFO", "GitHub issue migrated to correct repo (emitted by yoke_core.engines.doctor)"),
    ("ItemStatusChanged", "lifecycle", "item_status_change", "yoke_core.api.service_client", "STATUS", "Item status transition (emitted by yoke_core.api.service_client)"),
    ("LaneRoutingDecision", "workflow", "lane_routing", "cli", "INFO", "Emitted from shared post-decision path for lane routing outcomes"),
    ("LeaseAcquired", "lifecycle", "lease_lifecycle", "yoke_core.domain.coordination_leases", "INFO", "A coordination lease was acquired for a shared-operation key (project_id, lease_key). Carries lease_id, project_id, lease_key, session_id, actor_id, acquired_at, heartbeat_at."),
    ("LeaseHeartbeated", "lifecycle", "lease_lifecycle", "yoke_core.domain.coordination_leases", "INFO", "A live coordination lease's heartbeat_at was refreshed. Carries lease_id, project_id, lease_key, session_id, heartbeat_at."),
    ("LeaseReleased", "lifecycle", "lease_lifecycle", "yoke_core.domain.coordination_leases", "INFO", "A coordination lease was released with reason. Carries lease_id, project_id, lease_key, session_id, release_reason, released_at."),
    ("MergeBranchPushFailed", "lifecycle", "merge_lifecycle", "merge_worktree", "ERROR", "Merge branch push failed before pull request handling"),
    ("MergeBranchPushed", "lifecycle", "merge_lifecycle", "merge_worktree", "INFO", "Merge branch push succeeded before pull request handling"),
    ("MergeEngineFailed", "lifecycle", "merge_lifecycle", "merge_worktree", "ERROR", "Merge engine failed before completion"),
    ("MergeEngineStarted", "lifecycle", "merge_lifecycle", "merge_worktree", "INFO", "Merge engine started for the selected branch and target"),
    ("MergeEngineSucceeded", "lifecycle", "merge_lifecycle", "merge_worktree", "INFO", "Merge engine completed successfully"),
    ("LocalVerificationAcceptedAsCiSubstitute", "lifecycle", "merge_lifecycle", "merge_worktree", "INFO", "Merge accepted a non-empty PASS verdict in items.test_results as the evidence substitute when the PR had no required CI checks configured"),
    ("MergeBlockedNoVerificationEvidence", "lifecycle", "merge_lifecycle", "merge_worktree", "ERROR", "Merge refused: PR had no required CI checks AND items.test_results was empty or contained a failure signature"),
    ("MergePullRequestCiFailed", "lifecycle", "merge_lifecycle", "merge_worktree", "ERROR", "Pull request CI checks failed or could not be confirmed"),
    ("MergePullRequestCiPassed", "lifecycle", "merge_lifecycle", "merge_worktree", "INFO", "Pull request CI checks completed successfully"),
    ("MergePullRequestCiSkipped", "lifecycle", "merge_lifecycle", "merge_worktree", "INFO", "Pull request had no required CI checks configured; the merge gate fell through to the items.test_results local-verification evidence path"),
    ("MergePullRequestCreateFailed", "lifecycle", "merge_lifecycle", "merge_worktree", "ERROR", "Pull request creation failed before merge"),
    ("MergePullRequestCreated", "lifecycle", "merge_lifecycle", "merge_worktree", "INFO", "Pull request was created for the merge branch"),
    ("MergePullRequestMergeFailed", "lifecycle", "merge_lifecycle", "merge_worktree", "ERROR", "Pull request merge step failed"),
    ("MergePullRequestMergeRetried", "lifecycle", "merge_lifecycle", "merge_worktree", "INFO", "Pull request merge step retried after transient GraphQL propagation state"),
    ("MergePullRequestMergeStarted", "lifecycle", "merge_lifecycle", "merge_worktree", "INFO", "Pull request merge step started"),
    ("MergePullRequestReused", "lifecycle", "merge_lifecycle", "merge_worktree", "INFO", "Existing pull request was reused for the merge branch"),
    ("MergeTargetPushFailed", "lifecycle", "merge_lifecycle", "merge_worktree", "ERROR", "Merge target branch push failed before validation"),
    ("MergeTargetStale", "lifecycle", "merge_lifecycle", "merge_worktree", "ERROR", "Merge target branch moved during the merge window"),
    ("MergeTargetValidated", "lifecycle", "merge_lifecycle", "merge_worktree", "INFO", "Merge target branch was validated before merge execution"),
    ("MergeVerificationFailed", "lifecycle", "merge_lifecycle", "merge_worktree", "ERROR", "Merged branch ancestry verification failed after merge"),
    ("MergeVerificationPassed", "lifecycle", "merge_lifecycle", "merge_worktree", "INFO", "Merged branch ancestry was verified in the target branch"),
    ("MigrationCompleted", "system", "system", "yoke_core.domain.migration_harness_core", "INFO", "Expected low-cadence governed-migration completion event; retained active because migration applies are rare but still part of the live migration harness."),
    ("MigrationModuleRetireSkipped", "lifecycle", "migration_apply", "yoke_core.domain.migration_auto_retire", "INFO", "Expected low-cadence migration auto-retire skip emitted when install topology or audit evidence prevents module retirement."),
    ("MigrationRolledBack", "system", "system", "yoke_core.domain.migration_harness_core", "ERROR", "Expected low-cadence governed-migration rollback alarm emitted when migration verification fails and backup restore runs."),
    ("NextActionChosen", "workflow", "session_directive", "cli", "STATUS", "The core chose a next-action directive for an offered session"),
    ("PathIntegrityFailureDetected", "lifecycle", "path_integrity", "yoke_core.domain.path_integrity_runs", "WARN", "Path-integrity verifier recorded an invariant failure"),
    ("PathIntegrityRepairApplied", "lifecycle", "path_integrity", "yoke_core.domain.path_integrity_repair", "INFO", "Path-integrity repair operation applied to a verifier finding"),
    ("PathIntegrityRunCompleted", "lifecycle", "path_integrity", "yoke_core.domain.path_integrity_runs", "INFO", "Path-integrity verifier run closed with pass/fail/skip status"),
    ("PathIntegrityRunStarted", "lifecycle", "path_integrity", "yoke_core.domain.path_integrity_runs", "INFO", "Path-integrity verifier run opened"),
    ("PreviewEnvCleaned", "lifecycle", "preview_env", "deployment-runs-db", "INFO", "Preview deployment environment cleaned up after a run lane released it."),
    ("PreviewEnvCreated", "lifecycle", "preview_env", "deployment-runs-db", "INFO", "Preview deployment environment created for a run lane."),
    ("PreviewEnvOverwritten", "lifecycle", "preview_env", "deployment-runs-db", "INFO", "Occupied preview environment was overwritten by a new run lane claim."),
    ("QARequirementCreated", "lifecycle", "qa_lifecycle", "qa-db", "INFO", "QA requirement created and attached to item, task, or deployment run"),
    ("QARequirementUpdated", "lifecycle", "qa_lifecycle", "qa-db", "INFO", "QA requirement field updated via qa requirement-update"),
    ("QARequirementWaived", "lifecycle", "qa_lifecycle", "qa-db", "STATUS", "QA requirement waived with rationale"),
    ("QARunCompleted", "lifecycle", "qa_execution", "qa-db", "INFO", "QA run completed with verdict"),
    ("RetiredSchemaResurrectionAttempt", "system", "schema_guard", "yoke_core.domain.retired_schema_registry", "WARN", "Ambient init/bootstrap attempted to re-add a column registered in runtime/api/domain/retired_schema_surfaces.yaml; the ADD COLUMN was skipped. Context names project, table, column, caller, and the retiring migration module."),
    ("SchedulerOfferSkipped", "audit", "scheduler_selection", "backend", "INFO", "A scheduler offer was skipped before claim acquisition. Carries session_id, item_id (or process_key), recommended_action, skip_reason (stale_lifecycle, live_claim_conflict, recoverable_substrate, process_disabled_by_config, ...), current_status, claim_holder_session_id, claim_id, claimed_at, chain_step. Drives within-chain skip/cooldown memory."),
    ("SMLChangeApproved", "lifecycle", "strategize", "strategize-skill", "STATUS", "SML change approved by operator"),
    ("SMLChangeProposed", "lifecycle", "strategize", "strategize-skill", "INFO", "SML change proposed to operator"),
    ("SMLRefreshCompleted", "lifecycle", "strategize", "strategize-skill", "INFO", "SML refresh phase completed"),
    ("SectionDeleted", "system", "data_mutation", "cli", "INFO", "item_sections row deleted and body regenerated"),
    ("SectionUpserted", "system", "data_mutation", "cli", "INFO", "item_sections row upserted and body regenerated"),
    ("SessionCwdBindingFailOpen", "lifecycle", "session_cwd", "yoke_core.domain.lint_session_cwd_emit", "WARN", "Expected low-cadence session-cwd fallback alarm emitted when cwd binding cannot be resolved and the guard falls open."),
    ("SessionCwdBindingHealthCheckFailed", "lifecycle", "session_cwd", "yoke_core.domain.lint_session_cwd_emit", "WARN", "Expected low-cadence doctor alarm emitted when session-cwd binding health detects inconsistent worktree binding."),
    ("HarnessSessionEndRejectedActiveClaim", "system", "session_lifecycle", "api", "WARN", "end_session() rejected termination because the session holds active claims"),
    ("HarnessSessionEndReleasedClaims", "system", "session_lifecycle", "api", "INFO", "A session-end force path released one or more active claims before ending the session"),
    ("HarnessSessionEnded", "system", "session_lifecycle", "api", "INFO", "A session has been ended (no active claims at termination time)"),
    ("HarnessSessionHookFailed", "system", "session_hook_failure", "api", "WARN", "Emitted when a Claude/Codex Stop or SessionEnd hook fails to complete cleanly (DB contention or cleanup exception). Carries hook_event, executor, reason, latency_ms, stdin_state, session_id_source."),
    ("HarnessSessionOffered", "system", "session_offer", "cli", "INFO", "A harness session offered itself to Yoke for work assignment"),
    ("SessionOfferInvariantFailed", "workflow", "session_offer_invariant", "yoke_core.domain.session_offer_invariant_events", "WARN", "Charge-invariant guard refused to emit a directive after an offer-time claim was acquired; the cleanup helper released the claim (when present) so a normal session-end no longer returns ACTIVE_CLAIM. Carries action, selected_item, schedule_selected_item, new_claim {claim_id, item_id}, retry_skip_summary, invariant_message, surface (cli|http), release_outcome."),
    ("SessionOfferLaneOverrideIgnored", "system", "session_offer_lane_override_ignored", "yoke_core.domain.sessions_offer_lane", "WARN", "session-offer received a caller-supplied execution_lane (CLI --lane or HTTP body) that disagreed with the authoritative harness_sessions.execution_lane. The server uses the row value; the event records caller_supplied, row_lane, resolved_lane for audit."),
    ("HarnessSessionModelRefreshed", "system", "session_lifecycle", "runtime.harness.hook_runner", "INFO", "Emitted when a placeholder ``harness_sessions.model`` was upgraded to the real model ID from the transcript. Context: previous_model, refreshed_model, hook_source (PreToolUse / Stop / SessionEnd). Primarily a diagnostic for VS Code sessions where SessionStart arrives without a model field."),
    ("HarnessSessionSentFirstUserPromptSubmit", "system", "session_lifecycle", "runtime.harness.hook_runner", "INFO", "First UserPromptSubmit hook for this session has been handled (orientation block rendered). Distinct from HarnessSessionStarted, which fires earlier from the SessionStart hook when the harness_sessions row is inserted."),
    ("HarnessSessionStaleReclaimed", "system", "session_lifecycle", "api", "INFO", "Emitted by the shared stale-session reclaimer when an idle session is force-ended. Carries stale_minutes, last_event_at, released_claim_count, executor, reason."),
    ("HarnessSessionStarted", "system", "session_lifecycle", "runtime.harness.hook_runner", "INFO", "A new session was registered in harness_sessions (emitted from the SessionStart hook via runtime.harness.hook_runner)"),
    ("HarnessSessionStopped", "system", "session_lifecycle", "yoke_core.domain.agent_stop", "INFO", "Session stopped via Claude Code's Stop hook (emitted by yoke_core.domain.agent_stop). Context includes stop_reason (completed/auto_committed/unexpected_stop)."),
    ("SkipHopPerformed", "lifecycle", "status", "advance-skip", "STATUS", "Operator-asserted skip-phase hop (--skip-polish or --skip-refine on /yoke advance)"),
    ("StrategizeCompleted", "lifecycle", "strategize", "strategize-skill", "STATUS", "Strategize session completed"),
    ("StrategizeStarted", "lifecycle", "strategize", "strategize-skill", "STATUS", "Strategize session started"), ("StrategyDocCreated", "workflow", "strategy_doc", "yoke_core.domain.handlers.strategy_docs_create", "INFO", "Strategy doc row created through the strategy.doc.create function id; the per-project strategy_docs table is the authority and the project's gitignored local .yoke/strategy/ view re-renders from it. Context carries slug, project_id, project_slug, new_bytes."), ("StrategyDocReplaced", "workflow", "strategy_doc", "yoke_core.domain.handlers.strategy_docs", "INFO", "Strategy doc content replaced through the strategy.doc.replace or strategy.ingest.run function ids; the per-project strategy_docs table is the authority and the project's gitignored local .yoke/strategy/ view re-renders from it. Context carries slug, project_id, project_slug, old_bytes, new_bytes, source (replace|ingest)."), ("StrategyDefaultsSeeded", "workflow", "strategy_doc", "yoke_core.domain.handlers.strategy_docs_seed", "INFO", "Cold-start placeholder strategy rows minted for a project with no corpus via strategy.seed_defaults.run (also invoked server-side by the install bundle). Context carries project_id, project_slug, seeded slugs."),
    ("StrategyDocArchived", "workflow", "strategy_doc", "yoke_core.domain.handlers.strategy_docs_archive", "INFO", "Strategy doc archived via the strategy.doc.archive function id: archived_at is stamped on the strategy_docs row and the rendered view relocates to .yoke/strategy/archive/<slug>.md. The doc stays a full, editable row (unarchive restores it). Context carries slug, project_id, project_slug, archived."),
    ("StrategyDocUnarchived", "workflow", "strategy_doc", "yoke_core.domain.handlers.strategy_docs_archive", "INFO", "Strategy doc unarchived via the strategy.doc.unarchive function id: archived_at is cleared on the strategy_docs row and the rendered view moves back to the active .yoke/strategy/<slug>.md location. Context carries slug, project_id, project_slug, archived."),
    ("SyncFailed", "system", "sync_failure", "yoke_core.api.service_client", "WARN", "GitHub sync failure (emitted by yoke_core.api.service_client)"),
    ("TaskStatusChanged", "lifecycle", "task_status_change", "yoke_core.domain.epic", "STATUS", "Epic task status transition (migrated from epic_task_history)"),
    ("HarnessLifecycleMutationDetected", "system", "tool_call", "yoke_core.domain.observe", "WARN", "PostToolUse lifecycle-sensitive anomaly detected (reclassified from HarnessToolCallCompleted when the command mutated items/epic_tasks/events directly)"),
    ("HarnessToolCallCompleted", "system", "tool_call", "yoke_core.domain.observe", "INFO", "Tool call completed successfully (emitted by yoke_core.domain.observe)"),
    ("HarnessToolCallDenied", "audit", "tool_call", "yoke_core.domain.observe", "WARN", "PreToolUse guardrail denied a tool call (emitted by Yoke-owned lint deniers via the shared emit_denial_event helper)"),
    ("HarnessToolCallFailed", "system", "tool_call", "yoke_core.domain.observe", "WARN", "Tool call failed (emitted by yoke_core.domain.observe)"),
    ("HarnessToolCallStarted", "system", "tool_call", "yoke_core.domain.observe", "INFO", "Tool call started (emitted by yoke_core.domain.observe_pre PreToolUse)"),
    ("HarnessToolCallStructuredExit", "system", "tool_call", "yoke_core.domain.observe", "INFO", "Expected flow-control exit reclassified from HarnessToolCallFailed"),
    ("HookDispatchTelemetry", "system", "hook_dispatch", "runtime.harness.hook_runner", "INFO", "Runner-native summary emitted once per hook invocation by runtime.harness.hook_runner.telemetry. Carries hook_event, executor, chain_length, decision_outcome, session_id, item_id, tool_name, duration_ms."),
    ("HookExecutionFailed", "system", "hook_execution_failure", "runtime.harness.hook_runner", "WARN", "Runner-native event emitted when a hook chain step fails (import error, missing evaluate, subprocess timeout, decode error, exception, or nonzero exit). Carries module, hook_event, executor, failure, session_id, item_id, tool_name, duration_ms."),
    ("HookGuardrailEvaluated", "system", "hook_guardrail_evaluated", "runtime.harness.hook_runner", "DEBUG", "Runner-native per-chain-step event recording one guardrail evaluation. Carries module, hook_event, executor, decision_outcome, session_id, item_id, tool_name, duration_ms. DEBUG severity: highest-volume event in the system and redundant with HookDispatchTelemetry (per-invocation aggregate) + HarnessToolCallDenied/HookExecutionFailed (WARN); dropped at the default INFO write floor, capturable on demand by lowering severity_config to DEBUG. Suppression-token audit evidence rides on HarnessToolCallDenied with event_outcome='suppression_attempted'."),
    ("VerdictRendered", "workflow", "verdict_rendered", "shepherd", "STATUS", "Shepherd verdict rendered (emitted from shepherd_verdicts)"),
    ("WorkClaimed", "system", "session_lifecycle", "api", "INFO", "A work unit was claimed by a session"),
    ("WorkHandedOff", "system", "session_lifecycle", "api", "INFO", "A work claim has been handed off from one session to another"),
    ("WorktreeHandoffEmitted", "lifecycle", "worktree_handoff", "yoke_core.domain.worktree_handoff", "STATUS", "RETIRED — parent-stop semantics replaced by per-call claim-based lint authority; worktree creation is no longer a session boundary."),
    ("SessionExecutionScopeChanged", "lifecycle", "session_execution_scope", "yoke_core.domain.session_execution_scope", "STATUS", "RETIRED — session-envelope execution scope replaced by per-call claim-based lint authority (lint_session_cwd reads work_claims directly)."),
    ("OperatorClaimOverride", "system", "session_lifecycle", "api", "WARN", "Operator manually released a stranded claim via human-only override"),
    ("OperatorLeaseRelease", "system", "lease_lifecycle", "api", "WARN", "Operator manually released a stranded coordination lease via human-only override"),
    ("PathClaimRegistered", "lifecycle", "path_claim", "yoke_core.domain.path_claims_events", "INFO", "Path claim registered (planned or blocked) for an item via the on-ramp surface"),
    ("PathClaimRegistrationBlocked", "lifecycle", "path_claim", "yoke_core.domain.path_claims_events", "WARN", "Path-claim registration rejected by the lifecycle layer (overlap, invalid actor, invalid target set)"),
    ("PathClaimActivated", "lifecycle", "path_claim", "yoke_core.domain.path_claims_events", "INFO", "Path claim activated — door lock acquired against pinned base snapshot"),
    ("PathClaimActivationBlocked", "lifecycle", "path_claim", "yoke_core.domain.path_claims_events", "WARN", "Path-claim activation rejected (overlap raced ahead, upstream not released)"),
    ("PathClaimAmended", "lifecycle", "path_claim", "yoke_core.domain.path_claims_events", "INFO", "Path claim amended (widen, narrow, or cancel-amendment) via the sanctioned amendment surface"),
    ("PathClaimAmendmentBlocked", "lifecycle", "path_claim", "yoke_core.domain.path_claims_events", "WARN", "Path-claim amendment rejected (incompatible widen, narrow would orphan committed work, claim not amendable)"),
    ("PathClaimReleased", "lifecycle", "path_claim", "yoke_core.domain.path_claims_events", "INFO", "Path claim released — work merged or lineage ended peacefully"),
    ("PathClaimCancelled", "lifecycle", "path_claim", "yoke_core.domain.path_claims_events", "INFO", "Path claim cancelled — lineage abandoned before reaching the integration target"),
    ("PathClaimBoundaryCheckPassed", "lifecycle", "path_claim", "yoke_core.domain.path_claims_events", "INFO", "Committed-git boundary check passed at a lifecycle gate (valid / drifted / rename-resolved)"),
    ("PathClaimBoundaryCheckBlocked", "lifecycle", "path_claim", "yoke_core.domain.path_claims_events", "WARN", "Committed-git boundary check blocked a lifecycle gate (committed work outside declared coverage or unresolved worktree drift)"),
    ("PathClaimCoordinationOnlyRepaired", "lifecycle", "path_claim", "yoke_core.domain.path_claims_blocked_coordination_repair", "INFO", "Path claim stranded in state='blocked' under the legacy coord-only mutex or upstream-of-blocks classifier was flipped back to state='planned' by the advance-time repair sweep. Context carries claim_id, prior_blocked_reason, new_state, and directional_release (true for the upstream-of-blocks flip, false for the legacy coord-only flip)."),
    ("PathClaimOverride", "lifecycle", "path_claim", "yoke_core.domain.path_claims_events_override", "WARN", "Operator-collision approval — last-resort permission for a path claim to proceed past a blocking claim or revalidation conflict"),
    ("PathClaimBlockedReasonRefreshed", "lifecycle", "path_claim", "yoke_core.domain.path_claims_dependency_propagation", "INFO", "Path-claim blocked_reason refreshed to name a surviving non-terminal upstream after the previously-named upstream released."),
    ("PathTargetPlanned", "lifecycle", "path_target", "yoke_core.domain.path_targets_events", "INFO", "A path_targets row was minted (or re-planned from abandoned) with materialization_state='planned' for an exact future path"),
    ("PathTargetTentative", "lifecycle", "path_target", "yoke_core.domain.path_targets_events", "INFO", "A path_targets row was minted (or re-planned from abandoned) with materialization_state='tentative' for an exact predicted-but-uncertain future path"),
    ("PathTargetMaterialized", "lifecycle", "path_target", "yoke_core.domain.path_targets_events", "INFO", "A planned or tentative path_targets row was flipped to materialization_state='observed' on snapshot refresh, preserving claim identity across the future->live transition"),
    ("PathTargetAbandoned", "lifecycle", "path_target", "yoke_core.domain.path_targets_events", "INFO", "A planned or tentative path_targets row was flipped to materialization_state='abandoned' because its owning claim/item moved on"),
    ("PathTargetSymlinkCanonicalized", "lifecycle", "path_claim", "yoke_core.domain.path_claims_events_symlink", "INFO", "Symlink-aware path-claim registration paired an in-repo symlink target_id with its canonical-name target_id so the claim covers both. Context carries claim_id, symlink_path_string, canonical_path_string, symlink_target_id, canonical_target_id."),
    ("PathTargetSymlinkSkipped", "lifecycle", "path_claim", "yoke_core.domain.path_claims_events_symlink", "INFO", "Symlink-aware path-claim registration skipped canonicalization because the symlink points outside the project tree or is dangling. Context carries claim_id, symlink_path_string, reason, target_attempt, symlink_target_id."),
    ("HarnessSessionStaleSweepCompleted", "system", "session_lifecycle", "api", "INFO", "Stale-session sweep completed — emitted even when zero sessions reclaimed"),
    ("WorkReclaimed", "system", "session_lifecycle", "api", "INFO", "A stale session has been reclaimed and its claims released"),
    ("ReclaimAborted", "system", "session_lifecycle", "api", "INFO", "Stale-eligible reclaim aborted at the mutation boundary because fresh activity was observed. Carries scope (item_claim or session_cleanup), original_session_id, attempting_session_id, claim_id, executor, effective_ttl_minutes, original_session_last_heartbeat, original_session_last_event_at, abort_reason."),
    ("WorkReleased", "system", "session_lifecycle", "api", "INFO", "A work claim has been released"),
    ("ItemClaimReleaseFailed", "system", "session_lifecycle", "yoke_core.domain.sessions_lifecycle_release_failure", "WARN", "release_item_claim_for_execution attempted a release but did not succeed (not_owned/already_terminal/item_not_found/domain_error). Carries item_id, caller_session_id, holder_session_id, failure_reason, target_status, release_reason_intent."),
    ("ItemClaimReleaseRefused", "system", "session_lifecycle", "yoke_core.domain.sessions_lifecycle_release_precondition", "WARN", "Release-precondition invariant: release_work_claim_for_execution refused a non-terminal release on an item target because the session's chain checkpoint lacks durable terminal evidence (chainable=True AND handler_outcome not in TERMINAL_OUTCOMES). Carries prior_owner_session_id, item_id, claim_id, release_reason_intent, checkpoint_outcome, checkpoint_chainable, failure_reason='non_terminal_release_refused'."),
    ("ItemClaimReleaseOverride", "system", "session_lifecycle", "yoke_core.domain.sessions_lifecycle_release_precondition", "WARN", "Operator bypass: release-work-claim --allow-non-terminal proceeded despite a non-terminal intent without terminal-checkpoint evidence. Carries prior_owner_session_id, item_id, claim_id, release_reason_intent, operator_rationale."),
    ("SessionReactivatedWithReleasedClaims", "system", "session_lifecycle", "yoke_core.domain.sessions_lifecycle_reactivation", "INFO", "Session reactivated after SessionEnd with prior session-ended work claims. Surface event for the slim resume block; paired with SessionReactivationReacquiredClaims when the receipt of conditional auto-reacquire fires. Carries session_id, released_claim_count, released_claims."),
    ("HarnessSessionEndDeferred", "system", "session_lifecycle", "yoke_core.domain.sessions_lifecycle_destructive_guard", "INFO", "Transient SessionEnd refused destruction because a chainable checkpoint still has budget. Carries session_id, defer_reason (chain_pending), agent_presence_evidence, active_claim_count, claim_details."),
    ("SessionReactivationReacquiredClaims", "system", "session_lifecycle", "yoke_core.domain.sessions_lifecycle_reactivation", "INFO", "Receipt for the conditional auto-reacquire path on reactivation. Carries session_id, reacquired_count, conflict_count, claim_details ({outcome: reacquired|conflict, target}). Falls through to advisory only when another session legitimately holds the target."),
    ("HarnessSessionResumeBlockShown", "system", "session_lifecycle", "yoke_core.domain.sessions_resume_block", "INFO", "Once-per-reactivation marker emitted by the hook runner after it renders the slim resume block to the operator. Carries session_id, harness_event (UserPromptSubmit|SessionStart), reactivation_event_id, reacquired, advisory_only."),
    ("QARunCaptured", "lifecycle", "qa_execution", "yoke_core.domain.qa_execution", "INFO", "QA run captured with only an execution_status set (no verdict yet); sibling of QARunCompleted that fires once a verdict is recorded."),
    ("ReflectionMarkerParseFailed", "domain", "reflection_marker_parse_failed", "yoke_core.domain.reflection_capture_field_note", "WARN", "Subagent reflection block carried a field_note_kind marker whose value is outside the closed enum (failed|new|unclear|observation). The reflection itself was captured as plain text; the field-note was NOT fired. Context carries raw_value, valid_values, agent, entry_context, body_preview so operators can surface stale PM/PD body teaching."),
    ("ReflectionCaptureHookFired", "system", "tool_call", "yoke_core.domain.reflection_capture_hook", "INFO", "PostToolUse Agent-tool hook fired and called capture_reflections. Carries blocks_seen, blocks_parsed_successfully, blocks_skipped_known_falsepositive, blocks_unrecognized, blocks_partial_no_end_marker, entries_persisted, entries_duplicate_skipped, entries_persist_failed, error_count, tool_use_id, subagent_type, role, project."),
    ("ReflectionCaptureHookUnhandled", "domain", "reflection_unhandled", "yoke_core.domain.reflection_capture_hook", "WARN", "PostToolUse Agent-tool hook observed at least one reflection block with no matching shape parser. Carries blocks_unrecognized count plus raw_examples (each: excerpt + classification_attempt) so operators can grow the parser to cover the new shape, fixed by HC-reflection-capture-unhandled (24h WARN surface)."), ("ReflectionCapturePersistFailed", "domain", "reflection_capture", "yoke_core.domain.reflection_capture", "WARN", "persist_entries swallowed an exception while inserting one parsed reflection entry into ouroboros_entries. Carries agent, category, body_excerpt (first 200 chars), exception_type so operators can surface silent drops; backed by HC-reflection-capture-persist-failed (24h WARN surface)."),
    ("ClaimReacquiredAfterHandoff", "lifecycle", "session_lifecycle", "yoke_core.domain.work_claim_handoff", "INFO", "RETIRED — handoff semantics replaced by explicit polish/usher hops; emitter and registry row removed in commit 1fe83ff6c. Status retired so historical ledger rows do not register as rogue."), ("PathContextMigrated", "lifecycle", "path_context", "yoke_core.domain.path_context_continuity_cutover", "INFO", "RETIRED — emitter module deleted in commit 966d30574 alongside the path-posture doc-link cutover (docs/archive/decisions/path-posture-doc-links-cutover.md). Status retired so historical ledger rows do not register as rogue."),
    ("LeakAttempt", "system", "test_isolation", "runtime.api.test_events_isolation", "WARN", "RETIRED — test-isolation fixture emission that exercises the canonical-DB gate refusal path. Status retired so historical ledger rows do not register as rogue; the fixture itself remains in place to keep the gate exercised."), ("DeploymentEventMigrated", "lifecycle", "deployment", "yoke_core.domain.deployment", "INFO", "RETIRED — one-shot historical migration backfill event for the legacy deployment_events table; the emit site has been deleted. Status retired so historical event_id=migrate-dep-evt-N rows in the events ledger do not register as rogue."),
)
