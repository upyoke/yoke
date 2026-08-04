"""Corrective and severity-only event-registry updates."""

from __future__ import annotations

from typing import Tuple


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
    ("AgentSessionStarted", "system", "session_lifecycle", "runtime.harness.hook_runner", "Agent session started (emitted by runtime.harness.hook_runner)", "INFO"),
    ("SessionStarted", "system", "session_lifecycle", "runtime.harness.hook_runner", "A new session was registered in harness_sessions (emitted from the SessionStart hook via runtime.harness.hook_runner)", "INFO"),
    ("SessionSentFirstUserPromptSubmit", "system", "session_lifecycle", "runtime.harness.hook_runner", "First UserPromptSubmit hook for this session has been handled (orientation block rendered). Distinct from SessionStarted, which fires earlier from the SessionStart hook when the harness_sessions row is inserted.", "INFO"),
    ("SessionStartPayloadObserved", "system", "session_lifecycle", "runtime.harness.hook_runner", "Diagnostic: captures the SessionStart hook payload's top-level keys and model-field shape for surfaces where the docs' promise of payload.model fails in practice (e.g. VS Code)", "DEBUG"),
)


SEVERITY_ONLY_UPDATES: Tuple[Tuple[str, ...], ...] = (
    (
        "STATUS",
        (
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
