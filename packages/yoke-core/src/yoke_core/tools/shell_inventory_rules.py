"""Routing tables consumed by the shell migration inventory classifier.

These are pure-data lookup sets and dicts: which prefixes mark external
artifacts or harness boundaries, which basenames belong to each disposition
bucket (write authority, orchestration target, compatibility shim, DB wrapper,
keep-boundary, etc.), which Python home each shell file is destined for, and
which per-function overrides the parser should respect.

Splitting these out keeps the classifier module focused on logic rather than
data and lets each table grow without pushing the classifier over the file-line
budget.
"""

from __future__ import annotations

EXTERNAL_ARTIFACT_PREFIXES = (
    "projects/",
    "templates/",
)

HARNESS_BOUNDARY_PREFIXES = (
    "runtime/harness/",
)

THIN_MARKERS = (
    "thin launcher",
    "thin shell wrapper",
    "thin sourced shim",
    "thin shim over python",
    "shim target:",
    "delegates to yoke.api",
    "delegates to the python",
    "delegates correctness-critical decisions",
    "python-owned",
)

THIN_COMPATIBILITY_SHIMS = {
    "backlog-registry.sh",
    "hook-helpers.sh",
    "merge-lock.sh",
    "preview-board-art.sh",
    "sync-helper.sh",
    "sync-to-github.sh",
    "timing-helper.sh",
    "timing-report.sh",
}

WRITE_AUTHORITY = {
    "backlog-registry.sh",
    "sync-helper.sh",
    "sync-to-github.sh",
}

WRITE_AUTHORITY_TICKETS = {
    "backlog-registry.sh": "backlog-write-authority-retirement",
    "sync-helper.sh": "github-sync-write-authority-retirement",
    "sync-to-github.sh": "github-sync-write-authority-retirement",
}

ORCHESTRATION_TARGETS = {
    "browser-exec.sh",
    "browser-run-scenario.sh",
    "browser-snapshot.sh",
    "deploy-pipeline.sh",
    "deploy-qa-recorder.sh",
    "merge-worktree.sh",
    "persist-epic-simulation.sh",
    "qa-gate-check.sh",
}

ORCHESTRATION_TICKETS = {
    "browser-exec.sh": "browser-qa-orchestration-retirement",
    "browser-run-scenario.sh": "browser-qa-orchestration-retirement",
    "browser-snapshot.sh": "browser-qa-orchestration-retirement",
    "deploy-pipeline.sh": "deployment-orchestration-retirement",
    "deploy-qa-recorder.sh": "deployment-orchestration-retirement",
    "merge-worktree.sh": "merge-worktree-orchestration-retirement",
    "persist-epic-simulation.sh": "browser-qa-orchestration-retirement",
    "qa-gate-check.sh": "browser-qa-orchestration-retirement",
}

COMPATIBILITY_SHIMS = {
    "browser-run-scenario.sh",
    "deploy-pipeline.sh",
    "deploy-qa-recorder.sh",
    "item-db.sh",
    "project-db.sh",
    "qa-gate-check.sh",
    "schema-db.sh",
}

DB_WRAPPER_TICKETS = {
    "yoke-db.sh": "db-wrapper-retirement",
    "schema-db.sh": "db-wrapper-retirement",
    "item-db.sh": "db-wrapper-retirement",
    "project-db.sh": "db-wrapper-retirement",
    "shepherd-db.sh": "domain-db-wrapper-retirement",
    "ouroboros-db.sh": "domain-db-wrapper-retirement",
    "flow-db.sh": "domain-db-wrapper-retirement",
    "backup-db.sh": "domain-db-wrapper-retirement",
    "designs-db.sh": "domain-db-wrapper-retirement",
    "env-db.sh": "domain-db-wrapper-retirement",
    "harness-sessions-db.sh": "domain-db-wrapper-retirement",
    "release-notes-db.sh": "domain-db-wrapper-retirement",
}

UTILITY_TICKET_OVERRIDES = {
    "backfill-deployment-flows.sh": "deployment-orchestration-retirement",
    "browser-daemon.sh": "browser-qa-orchestration-retirement",
    "browser-worker.sh": "browser-qa-orchestration-retirement",
    "create-worktree.sh": "worktree-helper-retirement",
    "emit-denial.sh": "hook-session-helper-retirement",
    "generate-backlog-md.sh": "board-backlog-helper-retirement",
    "harness-session-end.sh": "hook-session-helper-retirement",
    "harness-session-env-init.sh": "hook-session-helper-retirement",
    "harness-session-start.sh": "hook-session-helper-retirement",
    "harness-session-stop.sh": "hook-session-helper-retirement",
    "hook-helpers.sh": "hook-session-helper-retirement",
    "install-worktree-deps.sh": "worktree-helper-retirement",
    "lint-sqlite-cmd.sh": "sqlite-lint-helper-retirement",
    "lint-event-registry.sh": "event-registry-lint-retirement",
    "merge-lock.sh": "merge-worktree-orchestration-retirement",
    "merge-settings.sh": "merge-worktree-orchestration-retirement",
    "on-agent-stop.sh": "hook-session-helper-retirement",
    "on-bash-complete.sh": "hook-session-helper-retirement",
    "preview-board-art.sh": "board-backlog-helper-retirement",
    "query-items.sh": "board-backlog-helper-retirement",
    "rebuild-board.sh": "board-backlog-helper-retirement",
    "render-body.sh": "board-backlog-helper-retirement",
    "resolve-item-worktree.sh": "worktree-helper-retirement",
    "resolve-paths.sh": "worktree-helper-retirement",
    "resolve-playwright-cache.sh": "worktree-helper-retirement",
    "service-client.sh": "hook-session-helper-retirement",
    "sqlite3-error-hook.sh": "hook-session-helper-retirement",
    "update-labels.sh": "github-sync-write-authority-retirement",
    "validate-buzz-pipeline.sh": "project-pipeline-validation-retirement",
    "verify-overlap.sh": "merge-worktree-orchestration-retirement",
    "write-to-main.sh": "merge-worktree-orchestration-retirement",
    "bootstrap-project.sh": "project-bootstrap-retirement",
    "check-prerequisites.sh": "source-dev-utility-retirement",
    "config-helper.sh": "source-dev-utility-retirement",
    "discovery-scan.sh": "source-dev-utility-retirement",
    "gh-issue.sh": "source-dev-utility-retirement",
    "gh-retry.sh": "source-dev-utility-retirement",
    "github-actions.sh": "source-dev-utility-retirement",
    "json-helper.sh": "source-dev-utility-retirement",
    "prd-validate.sh": "source-dev-utility-retirement",
    "timeout-portable.sh": "source-dev-utility-retirement",
    "timing-helper.sh": "source-dev-utility-retirement",
    "timing-report.sh": "source-dev-utility-retirement",
    "validate.sh": "source-dev-utility-retirement",
    "yaml-helper.sh": "source-dev-utility-retirement",
}

KEEP_BOUNDARY = {
    "doctor.sh",
    "backlog-resync.sh",
    "emit-event.sh",
    "observe-tool.sh",
    "observe-tool-pre.sh",
    "repair-status.sh",
    "restart-api.sh",
    "start-api.sh",
    "sync-progress.sh",
    "sync-task-body.sh",
    "sync-task-label.sh",
    "done-transition.sh",
    "update-status.sh",
}

PYTHON_HOME = {
    "backlog-resync.sh": "yoke_core.engines.resync",
    "doctor.sh": "yoke_core.engines.doctor",
    "emit-event.sh": "yoke_core.domain.emit_event",
    "merge-audit.sh": "yoke_core.engines.merge_audit",
    "observe-tool.sh": "yoke_core.domain.observe",
    "observe-tool-pre.sh": "yoke_core.domain.observe",
    "persist-epic-simulation.sh": "yoke_core.domain.epic",
    "repair-status.sh": "yoke_core.engines.repair_status",
    "sync-progress.sh": "yoke_core.domain.epic_task_sync",
    "sync-task-body.sh": "yoke_core.domain.epic_task_sync",
    "sync-task-label.sh": "yoke_core.domain.epic_task_sync",
    "done-transition.sh": "yoke_core.engines.done_transition",
    "update-status.sh": "yoke_core.domain.epic",
}

OWNER_LABELS = {
    "browser": "Browser QA",
    "deploy": "Deployment pipeline",
    "event": "Event platform",
    "hook": "Hook runtime",
    "merge": "Worktree merge",
    "qa": "QA platform",
    "registry": "Backlog registry",
    "test": "Shell test harness",
}

FUNCTION_HOME_OVERRIDES = {
    ("sync-helper.sh", "sync_frozen_label"): "yoke_core.domain.backlog_github_sync",
}

FUNCTION_RATIONALE_OVERRIDES = {
    (
        "sync-helper.sh",
        "sync_frozen_label",
    ): "Thin shell wrapper retained while sync-helper.sh still serves sourced callers.",
}
