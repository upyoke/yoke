"""Zero-shell zero-shell closeout lane routing tables for the shell migration inventory.

Each frozenset declares the relpath or basename allowlist owned by a specific
zero-shell closeout lane. The classifier consults ``closeout_ticket_for_non_test`` and
``closeout_ticket_for_test`` to attach the right closeout lane to every shell
file the inventory enumerates.
"""

from __future__ import annotations

from pathlib import Path

ZERO_SHELL_CLOSEOUT_DB_RELPATHS = frozenset(
    {
        ".agents/skills/yoke/scripts/yoke-db.sh",
        ".agents/skills/yoke/scripts/query-items.sh",
        ".agents/skills/yoke/scripts/schema-db.sh",
        ".agents/skills/yoke/scripts/project-db.sh",
        ".agents/skills/yoke/scripts/flow-db.sh",
        ".agents/skills/yoke/scripts/ouroboros-db.sh",
        ".agents/skills/yoke/scripts/release-notes-db.sh",
        ".agents/skills/yoke/scripts/harness-sessions-db.sh",
        ".agents/skills/yoke/scripts/backup-db.sh",
        ".agents/skills/yoke/scripts/env-db.sh",
        ".agents/skills/yoke/scripts/events-db.sh",
        ".agents/skills/yoke/scripts/shepherd-db.sh",
    }
)

ZERO_SHELL_CLOSEOUT_BACKLOG_RELPATHS = frozenset(
    {
        ".agents/skills/yoke/scripts/item-db.sh",
        ".agents/skills/yoke/scripts/backlog-registry.sh",
        ".agents/skills/yoke/scripts/sync-helper.sh",
        ".agents/skills/yoke/scripts/sync-to-github.sh",
        ".agents/skills/yoke/scripts/sync-progress.sh",
        ".agents/skills/yoke/scripts/sync-task-body.sh",
        ".agents/skills/yoke/scripts/sync-task-label.sh",
        ".agents/skills/yoke/scripts/update-status.sh",
        ".agents/skills/yoke/scripts/repair-status.sh",
        ".agents/skills/yoke/scripts/done-transition.sh",
        ".agents/skills/yoke/scripts/generate-backlog-md.sh",
        ".agents/skills/yoke/scripts/update-labels.sh",
        ".agents/skills/yoke/scripts/verify-claim.sh",
        ".agents/skills/yoke/scripts/approval-vocabulary.sh",
        ".agents/skills/yoke/scripts/check-ac-presence.sh",
        ".agents/skills/yoke/scripts/check-hard-blocks.sh",
        ".agents/skills/yoke/scripts/conduct-reviewed-handoff.sh",
        ".agents/skills/yoke/scripts/emit-denial.sh",
        ".agents/skills/yoke/scripts/normalize-ac-labels.sh",
        ".agents/skills/yoke/scripts/lint-write-path.sh",
    }
)

ZERO_SHELL_CLOSEOUT_HOOK_RELPATHS = frozenset(
    {
        ".agents/skills/yoke/scripts/observe-tool.sh",
        ".agents/skills/yoke/scripts/observe-tool-pre.sh",
        ".agents/skills/yoke/scripts/emit-event.sh",
        ".agents/skills/yoke/scripts/lint-event-registry.sh",
        ".agents/skills/yoke/scripts/doctor.sh",
        ".agents/skills/yoke/scripts/hook-helpers.sh",
        ".agents/skills/yoke/scripts/sqlite3-error-hook.sh",
        ".agents/skills/yoke/scripts/harness-session-end.sh",
        ".agents/skills/yoke/scripts/harness-session-env-init.sh",
        ".agents/skills/yoke/scripts/harness-session-start.sh",
        ".agents/skills/yoke/scripts/harness-session-stop.sh",
        ".agents/skills/yoke/scripts/on-agent-stop.sh",
        ".agents/skills/yoke/scripts/on-bash-complete.sh",
        ".agents/skills/yoke/scripts/service-client.sh",
        ".agents/skills/yoke/scripts/lint-main-commit.sh",
        ".agents/skills/yoke/scripts/lint-sqlite-cmd.sh",
        ".agents/skills/yoke/scripts/lint-tc-label.sh",
        ".agents/skills/yoke/scripts/git-pre-commit.sh",
    }
)

ZERO_SHELL_CLOSEOUT_BROWSER_RELPATHS = frozenset(
    {
        ".agents/skills/yoke/scripts/browser-worker.sh",
        ".agents/skills/yoke/scripts/browser-daemon.sh",
        ".agents/skills/yoke/scripts/browser-exec.sh",
        ".agents/skills/yoke/scripts/browser-run-scenario.sh",
        ".agents/skills/yoke/scripts/browser-snapshot.sh",
        ".agents/skills/yoke/scripts/backfill-deployment-flows.sh",
        ".agents/skills/yoke/scripts/deploy-pipeline.sh",
        ".agents/skills/yoke/scripts/deploy-qa-recorder.sh",
        ".agents/skills/yoke/scripts/github-actions.sh",
        ".agents/skills/yoke/scripts/validate-buzz-pipeline.sh",
        ".agents/skills/yoke/scripts/qa-gate-check.sh",
    }
)

ZERO_SHELL_CLOSEOUT_WORKTREE_RELPATHS = frozenset(
    {
        ".agents/skills/yoke/scripts/create-worktree.sh",
        ".agents/skills/yoke/scripts/install-worktree-deps.sh",
        ".agents/skills/yoke/scripts/merge-lock.sh",
        ".agents/skills/yoke/scripts/merge-settings.sh",
        ".agents/skills/yoke/scripts/merge-worktree.sh",
        ".agents/skills/yoke/scripts/persist-epic-simulation.sh",
        ".agents/skills/yoke/scripts/preview-board-art.sh",
        ".agents/skills/yoke/scripts/rebuild-board.sh",
        ".agents/skills/yoke/scripts/render-body.sh",
        ".agents/skills/yoke/scripts/resolve-item-worktree.sh",
        ".agents/skills/yoke/scripts/resolve-paths.sh",
        ".agents/skills/yoke/scripts/resolve-playwright-cache.sh",
        ".agents/skills/yoke/scripts/verify-overlap.sh",
        ".agents/skills/yoke/scripts/write-to-main.sh",
        ".agents/skills/yoke/scripts/prd-validate.sh",
    }
)

ZERO_SHELL_CLOSEOUT_UTILITY_RELPATHS = frozenset(
    {
        ".agents/skills/yoke/scripts/backlog-resync.sh",
        ".agents/skills/yoke/scripts/check-prerequisites.sh",
        ".agents/skills/yoke/scripts/config-helper.sh",
        ".agents/skills/yoke/scripts/discovery-scan.sh",
        ".agents/skills/yoke/scripts/gh-issue.sh",
        ".agents/skills/yoke/scripts/gh-retry.sh",
        ".agents/skills/yoke/scripts/json-helper.sh",
        ".agents/skills/yoke/scripts/migrate-to-sqlite.sh",
        ".agents/skills/yoke/scripts/timeout-portable.sh",
        ".agents/skills/yoke/scripts/timing-helper.sh",
        ".agents/skills/yoke/scripts/timing-report.sh",
        ".agents/skills/yoke/scripts/validate.sh",
        ".agents/skills/yoke/scripts/yaml-helper.sh",
        ".agents/skills/yoke/scripts/bootstrap-project.sh",
        ".agents/skills/yoke/scripts/executors/exec-auto.sh",
        ".agents/skills/yoke/scripts/executors/exec-ephemeral-verify.sh",
        ".agents/skills/yoke/scripts/executors/exec-health-check.sh",
        ".agents/skills/yoke/scripts/executors/exec-script.sh",
        "runtime/api/start-api.sh",
        "runtime/api/restart-api.sh",
        "runtime/install.sh",
    }
)

ZERO_SHELL_CLOSEOUT_RUNNER_RELPATHS = frozenset(
    {".agents/skills/yoke/scripts/lint-test-pipe.sh"}
)

ZERO_SHELL_CLOSEOUT_DB_TESTS = frozenset(
    {
        "test-backup-db.sh",
        "test-baseline-db.sh",
        "test-env-db.sh",
        "test-flow-db.sh",
        "test-harness-sessions-parity.sh",
        "test-items-progress.sh",
        "test-large-body-read.sh",
        "test-missing-flow.sh",
        "test-project-db.sh",
        "test-query-items-project.sh",
        "test-query-items.sh",
        "test-qa-tables.sh",
        "test-release-notes-db.sh",
        "test-schema-db.sh",
        "test-schema-extensions.sh",
        "test-schema-gate.sh",
        "test-shepherd-db.sh",
        "test-yoke-db-autoinit-guard.sh",
        "test-yoke-db-events-audit-diff.sh",
        "test-yoke-db-injection.sh",
        "test-yoke-db.sh",
    }
)

ZERO_SHELL_CLOSEOUT_BACKLOG_TESTS = frozenset(
    {
        "test-active-reconciliation.sh",
        "test-add-cleanup.sh",
        "test-advance-ac-gate.sh",
        "test-approval-vocabulary.sh",
        "test-backfill-task-labels-status.sh",
        "test-backlog-label-sync.sh",
        "test-backlog-registry-isolation.sh",
        "test-body-sync.sh",
        "test-cascade-task-status.sh",
        "test-check-ac-presence.sh",
        "test-check-hard-blocks.sh",
        "test-conduct-reviewed-handoff.sh",
        "test-dedup-body-scan.sh",
        "test-denial-events.sh",
        "test-done-nonce-gate.sh",
        "test-done-transition-deploy-guard.sh",
        "test-done-transition-result-file.sh",
        "test-done-transition-retry.sh",
        "test-done-transition-sim-gate.sh",
        "test-dry-run.sh",
        "test-frozen-label-sync.sh",
        "test-generate-backlog-md.sh",
        "test-issue-reviewed-implementation-preflight.sh",
        "test-item-status-events.sh",
        "test-lifecycle-mutation-guard.sh",
        "test-live-state-ac-tagging.sh",
        "test-merged-at-population.sh",
        "test-normalize-ac-labels.sh",
        "test-project-aware-sync.sh",
        "test-project-change-migration.sh",
        "test-repair-status.sh",
        "test-stale-body-guard.sh",
        "test-struct-field-safety.sh",
        "test-sync-body-silent-fail.sh",
        "test-sync-body-task.sh",
        "test-sync-empty-worktree.sh",
        "test-sync-progress-cross-project.sh",
        "test-sync-task-label.sh",
        "test-sync-to-github-cross-project.sh",
        "test-untracked-views.sh",
        "test-update-status.sh",
        "test-update-yok-prefix.sh",
        "test-verify-claim.sh",
    }
)

ZERO_SHELL_CLOSEOUT_HOOK_TESTS = frozenset(
    {
        "test-agent-frontmatter-hooks.sh",
        "test-bootstrap-helper.sh",
        "test-charge-decision-events.sh",
        "test-codex-entry.sh",
        "test-codex-hooks.sh",
        "test-db-error-hook.sh",
        "test-do-loop-chain-checkpoint.sh",
        "test-doctor-launcher.sh",
        "test-emit-event-correlation.sh",
        "test-emit-event-registry.sh",
        "test-emit-event.sh",
        "test-event-item-id.sh",
        "test-event-registry-enforcement.sh",
        "test-events-backfill.sh",
        "test-events-capture.sh",
        "test-events-compat-views.sh",
        "test-events-correlation-migration.sh",
        "test-events-helpers.sh",
        "test-events-insert-correlation.sh",
        "test-harness-routing.sh",
        "test-harness-session-identity.sh",
        "test-harness-session-resolver.sh",
        "test-hook-helpers.sh",
        "test-lint-event-registry.sh",
        "test-lint-tc-label.sh",
        "test-observe-tool-pre.sh",
        "test-on-bash-complete-root.sh",
        "test-repair-events-envelopes.sh",
        "test-session-attribution.sh",
    }
)

ZERO_SHELL_CLOSEOUT_BROWSER_TESTS = frozenset(
    {
        "test-advance-browser-qa.sh",
        "test-browser-artifact.sh",
        "test-browser-bootstrap.sh",
        "test-browser-daemon-parser.sh",
        "test-browser-scripts.sh",
        "test-browser-worker.sh",
        "test-deploy-pipeline.sh",
        "test-deploy-qa-recorder.sh",
        "test-eph-next-stage.sh",
        "test-github-actions.sh",
        "test-qa-executor-guard.sh",
        "test-qa-gate-check.sh",
        "test-satisfy-screenshot-evidence.sh",
        "test-validate-buzz-pipeline.sh",
    }
)

ZERO_SHELL_CLOSEOUT_WORKTREE_TESTS = frozenset(
    {
        "test-baseline-capture-worktree-safe.sh",
        "test-board-unknown-status.sh",
        "test-board-velocity-meter.sh",
        "test-board-velocity-sparkline.sh",
        "test-branch-checkout-detection.sh",
        "test-caveats-merge.sh",
        "test-create-epic-worktree.sh",
        "test-cross-project-audit.sh",
        "test-empty-branch-guard.sh",
        "test-epic-simulation-gate.sh",
        "test-finalize-worktree-commit.sh",
        "test-install-worktree-deps.sh",
        "test-merge-guard-yok552.sh",
        "test-merge-lock.sh",
        "test-merge-project-test-cmd.sh",
        "test-merge-worktree-validation.sh",
        "test-merge-worktree.sh",
        "test-no-inline-dep-ddl.sh",
        "test-persist-epic-simulation.sh",
        "test-rebuild-board-throttle.sh",
        "test-resolve-item-worktree.sh",
        "test-worktree-python-shadow.sh",
        "test-write-to-main.sh",
    }
)

ZERO_SHELL_CLOSEOUT_UTILITY_TESTS = frozenset(
    {
        "test-bootstrap-project.sh",
        "test-discovery-scan.sh",
        "test-temp-cleanup.sh",
        "test-timeout-portable.sh",
        "test-timing-helper.sh",
    }
)


def closeout_ticket_for_non_test(relpath: str) -> str | None:
    if relpath in ZERO_SHELL_CLOSEOUT_DB_RELPATHS:
        return "db-wrapper-retirement"
    if relpath in ZERO_SHELL_CLOSEOUT_BACKLOG_RELPATHS:
        return "backlog-lifecycle-shell-retirement"
    if relpath in ZERO_SHELL_CLOSEOUT_HOOK_RELPATHS or relpath.startswith("runtime/harness/"):
        return "hook-harness-shell-retirement"
    if relpath in ZERO_SHELL_CLOSEOUT_BROWSER_RELPATHS:
        return "browser-deployment-qa-shell-retirement"
    if relpath in ZERO_SHELL_CLOSEOUT_WORKTREE_RELPATHS:
        return "worktree-merge-board-shell-retirement"
    if relpath in ZERO_SHELL_CLOSEOUT_UTILITY_RELPATHS:
        return "utility-installer-executor-shell-retirement"
    if relpath in ZERO_SHELL_CLOSEOUT_RUNNER_RELPATHS:
        return "shell-test-runner-retirement"
    if relpath.startswith("projects/") or relpath.startswith("templates/"):
        return "external-artifact-shell-retirement"
    return None


def closeout_ticket_for_test(relpath: str) -> str:
    basename = Path(relpath).name
    if basename in ZERO_SHELL_CLOSEOUT_DB_TESTS:
        return "db-wrapper-retirement"
    if basename in ZERO_SHELL_CLOSEOUT_BACKLOG_TESTS:
        return "backlog-lifecycle-shell-retirement"
    if basename in ZERO_SHELL_CLOSEOUT_HOOK_TESTS:
        return "hook-harness-shell-retirement"
    if basename in ZERO_SHELL_CLOSEOUT_BROWSER_TESTS:
        return "browser-deployment-qa-shell-retirement"
    if basename in ZERO_SHELL_CLOSEOUT_WORKTREE_TESTS:
        return "worktree-merge-board-shell-retirement"
    if basename in ZERO_SHELL_CLOSEOUT_UTILITY_TESTS:
        return "utility-installer-executor-shell-retirement"
    return "shell-test-runner-retirement"
