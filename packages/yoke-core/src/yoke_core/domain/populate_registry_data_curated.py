"""Curated and corrective event-registry data tuples.

Sibling module of :mod:`yoke_core.domain.populate_registry`. Holds the
operator-authored data tables that drive the curated, corrective, and
severity-only update layers of the populator pipeline:

- :data:`CURATED_EVENTS`: events explicitly registered idempotently
  because they may not yet have call sites reachable by discovery.
- :data:`CORRECTIVE_UPDATES`: metadata overrides for events whose
  auto-inferred values need authoritative replacements.
- :data:`SEVERITY_ONLY_UPDATES`: bulk severity corrections for events
  already registered with correct kind and type.

The apply helpers in :mod:`yoke_core.domain.populate_registry_apply`
unpack these tuples in the column orders documented below. ``CURATED_EVENTS``
and ``CORRECTIVE_UPDATES`` share the column order
``(name, kind, event_type, service, description, severity)``.
``SEVERITY_ONLY_UPDATES`` is a tuple of ``(severity, (names...))`` pairs.
"""

from __future__ import annotations

from typing import Tuple


# Each entry is (name, kind, event_type, service, description, severity).
# These events are registered explicitly because they may not yet have call
# sites reachable by discovery (new platform events, Python-native emitters,
# etc.).  ``cmd_registry_add`` is idempotent, so repeated runs are safe.
CURATED_EVENTS: Tuple[Tuple[str, str, str, str, str, str], ...] = (
    # --- operator break-glass (manual psql rows; operator private break-glass runbook) ---
    (
        "OperatorBreakGlassSession",
        "system",
        "operator_break_glass",
        "psql",
        "Operator opened a non-Yoke-routed break-glass psql session against a project database; written by hand as the audit-first step of the operator's private break-glass runbook",
        "WARN",
    ),
    # --- event platform events ---
    (
        "TaskStatusChanged",
        "lifecycle",
        "task_status_change",
        "epic-db",
        "Epic task status transition (migrated from epic_task_history)",
        "STATUS",
    ),
    (
        "SyncFailed",
        "system",
        "sync_failure",
        "sync-helper",
        "GitHub sync failure (migrated from sync_failures)",
        "WARN",
    ),
    (
        "VerdictRendered",
        "workflow",
        "verdict_rendered",
        "shepherd",
        "Shepherd verdict rendered (emitted from shepherd_verdicts)",
        "STATUS",
    ),
    # --- task 006: QA platform events ---
    (
        "QARequirementCreated",
        "lifecycle",
        "qa_lifecycle",
        "qa-db",
        "QA requirement created and attached to item, task, or deployment run",
        "INFO",
    ),
    (
        "QARequirementWaived",
        "lifecycle",
        "qa_lifecycle",
        "qa-db",
        "QA requirement waived with rationale",
        "STATUS",
    ),
    (
        "QARequirementUpdated",
        "lifecycle",
        "qa_lifecycle",
        "qa-db",
        "QA requirement field updated via qa requirement-update",
        "INFO",
    ),
    (
        "QARunStarted",
        "lifecycle",
        "qa_execution",
        "qa-db",
        "QA run started (no verdict yet)",
        "INFO",
    ),
    (
        "QARunCompleted",
        "lifecycle",
        "qa_execution",
        "qa-db",
        "QA run completed with verdict",
        "INFO",
    ),
    (
        "QAArtifactAttached",
        "lifecycle",
        "qa_lifecycle",
        "qa-db",
        "QA artifact attached to a run (screenshot, log, trace)",
        "DEBUG",
    ),
    # --- task 001: Feed skill events ---
    (
        "FeedStarted",
        "lifecycle",
        "feed",
        "feed-skill",
        "Feed skill invocation started (SML materialization or graph refresh)",
        "STATUS",
    ),
    (
        "FeedCompleted",
        "lifecycle",
        "feed",
        "feed-skill",
        "Feed skill invocation completed (SML materialization or graph refresh)",
        "STATUS",
    ),
    # --- Corrective runtime events with stale test-derived metadata ---
    (
        "HarnessSessionSentFirstUserPromptSubmit",
        "system",
        "session_lifecycle",
        "runtime.harness.hook_runner",
        "First UserPromptSubmit hook for this session has been handled (orientation block rendered). Distinct from HarnessSessionStarted, which fires earlier from the SessionStart hook when the harness_sessions row is inserted.",
        "INFO",
    ),
    (
        "HarnessSessionStarted",
        "system",
        "session_lifecycle",
        "runtime.harness.hook_runner",
        "A new session was registered in harness_sessions (emitted from the SessionStart hook via runtime.harness.hook_runner)",
        "INFO",
    ),
    (
        "HarnessToolCallStarted",
        "system",
        "tool_call",
        "yoke_core.domain.observe",
        "Tool call started (emitted by yoke_core.domain.observe PreToolUse)",
        "INFO",
    ),
    (
        "HarnessToolCallCompleted",
        "system",
        "tool_call",
        "yoke_core.domain.observe",
        "Tool call completed successfully (emitted by yoke_core.domain.observe)",
        "INFO",
    ),
    (
        "HarnessToolCallFailed",
        "system",
        "tool_call",
        "yoke_core.domain.observe",
        "Tool call failed (emitted by yoke_core.domain.observe)",
        "WARN",
    ),
    (
        "HarnessToolCallDenied",
        "audit",
        "tool_call",
        "yoke_core.domain.observe",
        "PreToolUse guardrail denied a tool call (emitted by Yoke-owned lint deniers via the shared emit_denial_event helper)",
        "WARN",
    ),
    (
        "HarnessToolCallStructuredExit",
        "system",
        "tool_call",
        "yoke_core.domain.observe",
        "Expected flow-control exit reclassified from HarnessToolCallFailed",
        "INFO",
    ),
    (
        "HarnessLifecycleMutationDetected",
        "system",
        "tool_call",
        "yoke_core.domain.observe",
        "PostToolUse lifecycle-sensitive anomaly detected (reclassified from HarnessToolCallCompleted when the command mutated items/epic_tasks/events directly)",
        "WARN",
    ),
    (
        "DataLossDetected",
        "system",
        "db_alarm",
        "yoke_core.domain.db_error_hook",
        "Fatal alarm: row-count collapse detected in a critical DB table after DDL operation",
        "FATAL",
    ),
    # --- native Python emitter events ---
    (
        "FrontierComputed",
        "workflow",
        "frontier_computation",
        "frontier.py",
        "Frontier computed by core Python path",
        "INFO",
    ),
    (
        "DependencyGateEvaluated",
        "workflow",
        "dependency_gate",
        "dependency_planning.py",
        "Batch dependency gate evaluation summary",
        "INFO",
    ),
    (
        "FrontierStepSelected",
        "workflow",
        "scheduler_selection",
        "scheduler.py",
        "Scheduler finalized step selection",
        "INFO",
    ),
    (
        "LaneRoutingDecision",
        "workflow",
        "lane_routing",
        "sessions.py",
        "Lane routing outcome for selected scheduler step",
        "INFO",
    ),
    (
        "AdapterDispatchChosen",
        "workflow",
        "adapter_dispatch",
        "sessions.py",
        "Downstream adapter path chosen for charge/resume",
        "INFO",
    ),
    # --- external sign-in identity events ---
    (
        "ExternalIdentityLinked",
        "lifecycle",
        "external_identity",
        "yoke_core.domain.external_identities",
        "A verified external identity (issuer + subject) was bound to an actor",
        "INFO",
    ),
    (
        "SignInSucceeded",
        "lifecycle",
        "sign_in",
        "yoke_core.domain.sign_in_resolution",
        "External sign-in resolved to an actor (linked identity, invite acceptance, or auto-join)",
        "INFO",
    ),
    (
        "SignInRefused",
        "lifecycle",
        "sign_in",
        "yoke_core.domain.sign_in_resolution",
        "External sign-in was refused; context carries the refusal_reason kind",
        "WARN",
    ),
    (
        "ActorInviteCreated",
        "lifecycle",
        "actor_invite",
        "yoke_core.domain.actor_invites",
        "Operator created a pending actor invite for an email address",
        "INFO",
    ),
    (
        "ActorInviteAccepted",
        "lifecycle",
        "actor_invite",
        "yoke_core.domain.actor_invites",
        "A pending actor invite was accepted during sign-in resolution",
        "STATUS",
    ),
    (
        "ActorInviteRevoked",
        "lifecycle",
        "actor_invite",
        "yoke_core.domain.actor_invites",
        "Operator revoked a pending actor invite",
        "STATUS",
    ),
    (
        "AutoJoinDomainChanged",
        "lifecycle",
        "org_settings",
        "yoke_core.domain.external_identities",
        "Operator set or cleared the org auto-join email domain; context carries previous and new values",
        "STATUS",
    ),
)


# Corrective metadata for events that are already registered but whose
# auto-discovered values need to be overridden with authoritative values.
# Each entry is (name, kind, event_type, service, description, severity).
# The update is an UPDATE (not INSERT), so the event must already exist —
# the curated-add above ensures it does when necessary.
CORRECTIVE_UPDATES: Tuple[Tuple[str, str, str, str, str, str], ...] = (
    (
        "ItemStatusChanged",
        "lifecycle",
        "item_status_change",
        "yoke_core.api.service_client",
        "Item status transition (emitted by yoke_core.api.service_client)",
        "STATUS",
    ),
    (
        "SyncFailed",
        "system",
        "sync_failure",
        "yoke_core.api.service_client",
        "GitHub sync failure (emitted by yoke_core.api.service_client)",
        "WARN",
    ),
    (
        "HarnessSessionStopped",
        "system",
        "session_lifecycle",
        "yoke_core.domain.agent_stop",
        "Agent session stopped (emitted by yoke_core.domain.agent_stop). Context includes stop_reason (completed/auto_committed/unexpected_stop)",
        "INFO",
    ),
    (
        "GitHubCloseFailure",
        "system",
        "github_sync",
        "yoke_core.domain.update_status",
        "GitHub issue close failed (emitted by yoke_core.domain.update_status)",
        "WARN",
    ),
    (
        "IssueMigrated",
        "system",
        "github_sync",
        "yoke_core.engines.doctor",
        "GitHub issue migrated to correct repo (emitted by yoke_core.engines.doctor)",
        "INFO",
    ),
    (
        "TestEvent",
        "system",
        "test_event",
        "yoke_core.domain.events",
        "Test-only event used by the events-capture test harness",
        "INFO",
    ),
    # Retired session-hook owner: rewrite legacy owner_service to hook_runner.
    ("AgentSessionStarted", "system", "session_lifecycle", "runtime.harness.hook_runner", "Agent session started (emitted by runtime.harness.hook_runner)", "INFO"),
    ("SessionStarted", "system", "session_lifecycle", "runtime.harness.hook_runner", "A new session was registered in harness_sessions (emitted from the SessionStart hook via runtime.harness.hook_runner)", "INFO"),
    ("SessionSentFirstUserPromptSubmit", "system", "session_lifecycle", "runtime.harness.hook_runner", "First UserPromptSubmit hook for this session has been handled (orientation block rendered). Distinct from SessionStarted, which fires earlier from the SessionStart hook when the harness_sessions row is inserted.", "INFO"),
    ("SessionStartPayloadObserved", "system", "session_lifecycle", "runtime.harness.hook_runner", "Diagnostic: captures the SessionStart hook payload's top-level keys and model-field shape for surfaces where the docs' promise of payload.model fails in practice (e.g. VS Code)", "DEBUG"),
)


# Severity-only corrections for events already registered with correct kind
# and type but stale severity.  Applied in bulk.
SEVERITY_ONLY_UPDATES: Tuple[Tuple[str, ...], ...] = (
    (
        "STATUS",
        (
            "BaselinePromoted",
            "BaselineRecorded",
            "DriftReviewCompleted",
            "FrontierComputed",
            "NextActionChosen",
            "SMLChangeApproved",
            "StrategizeCompleted",
            "StrategizeStarted",
            "TaskStatusChanged",
            "VerdictRendered",
        ),
    ),
    (
        "STATUS",
        (
            "DeploymentRunExecuting",
            "DeploymentRunFailed",
            "DeploymentRunStageCompleted",
            "DeploymentRunStageFailed",
            "DeploymentRunStageStarted",
            "DeploymentRunSucceeded",
        ),
    ),
)
