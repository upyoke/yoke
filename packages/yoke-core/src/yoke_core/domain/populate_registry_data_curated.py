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

from yoke_core.domain.populate_registry_data_updates import (  # noqa: F401
    CORRECTIVE_UPDATES,
    SEVERITY_ONLY_UPDATES,
)

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
        "yoke_core.hooks",
        "First UserPromptSubmit hook for this session has been handled (orientation block rendered). Distinct from HarnessSessionStarted, which fires earlier from the SessionStart hook when the harness_sessions row is inserted.",
        "INFO",
    ),
    (
        "HarnessSessionStarted",
        "system",
        "session_lifecycle",
        "yoke_core.hooks",
        "A new session was registered in harness_sessions (emitted from the SessionStart hook via yoke_core.hooks). On a REACTIVATION the context also carries driver_surface, driver_version, driver_pid, driver_ppid, driver_pid_origin, and driver_hook_event — the process and hook event that revived the row. This record is unconditional: it does not depend on a wake attempt being in flight, and where one is, that attempt's evidence row is stamped from the same values so the two agree. A fresh registration carries no driver fields, because there the driving surface and the registered surface are the same row",
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
        "OrganizationDomainChanged",
        "lifecycle",
        "org_settings",
        "yoke_core.domain.external_identities",
        "Operator set or cleared the org identity domain; context carries previous and new values",
        "STATUS",
    ),
    # --- relay transport (spooled machine-side, emitted once a call lands) ---
    (
        "RelayTransportRetrySucceeded",
        "system",
        "relay_transport",
        "cli",
        "An HTTPS relay call needed more than one attempt and then landed; context carries the function, env, and attempt count, and the session id resolves the harness it ran under",
        "INFO",
    ),
    (
        "RelayTransportAttemptsExhausted",
        "system",
        "relay_transport",
        "cli",
        "An HTTPS relay call spent its whole attempt budget without an answer; context carries the function, env, and attempt count, and the session id resolves the harness it ran under",
        "WARN",
    ),
)
