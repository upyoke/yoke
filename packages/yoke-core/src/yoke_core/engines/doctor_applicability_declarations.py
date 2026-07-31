"""What each registered health check applies to.

Every check in the engine roster names its shape here, so the runner can
derive the applicable set for a given project and runtime instead of
shipping all of them everywhere and letting the mismatch pass silently. A
slug missing from this table is a declaration gap, not a licence to run
anywhere — :func:`undeclared_slugs` reports the gap and
``HC-doctor-applicability-declaration`` fails on it.

The shapes:

``_DB``
    Control-plane database only. Applies to every project on every runtime.
``_SRC``
    Reads the target project's source tree. Only a runner holding that
    checkout can answer it.
``_SELF``
    Reads the source tree of the project that owns this Yoke installation —
    its agent prompts, skills, docs, harness adapters, and code doctrine.
``_EXT`` / ``_EXT_SRC``
    Diagnoses a project other than the one that owns the installation.
``_MIGRATION`` / ``_EXT_HEALTH`` / ``_EXT_VPS``
    Needs a capability the project may not declare; without it the check has
    no subject to inspect.
"""

from __future__ import annotations

from typing import Dict, List

from yoke_core.engines.doctor_applicability import (
    CheckApplicability,
    PROJECT_SCOPE_EXTERNAL,
    PROJECT_SCOPE_SELF,
    UNIVERSAL,
)


_DB = UNIVERSAL
_SRC = CheckApplicability(requires_source_checkout=True)
_SELF = CheckApplicability(
    project_scope=PROJECT_SCOPE_SELF, requires_source_checkout=True,
)
_EXT = CheckApplicability(project_scope=PROJECT_SCOPE_EXTERNAL)
_EXT_SRC = CheckApplicability(
    project_scope=PROJECT_SCOPE_EXTERNAL, requires_source_checkout=True,
)
_MIGRATION = CheckApplicability(
    requires_source_checkout=True, required_capabilities=("migration_model",),
)
_EXT_HEALTH = CheckApplicability(
    project_scope=PROJECT_SCOPE_EXTERNAL,
    required_capabilities=("health-endpoint",),
)
_EXT_VPS = CheckApplicability(
    project_scope=PROJECT_SCOPE_EXTERNAL, required_capabilities=("vps-ssh",),
)


_SHAPES = (
    (_DB, (
        "architecture-impact-declaration", "backlog-hygiene", "backlog-quality",
        "blocked-flag-consistency", "blocked-items", "blocked-status-drift",
        "branch-protection-required-check", "cancelled-blocker-dependencies",
        "claim-boundary-audit", "coordination-leases-stale-or-orphan",
        "coordination-leases-unmerged-source", "deferred-items",
        "delegated-sync", "dependency-drift", "deploy-stage-integrity",
        "dispatch-chain", "duplicate-projects", "empty-task-worktree",
        "epic-task-scope-state", "epic-task-worktree",
        "epic-task-worktree-backfill", "epic-validation",
        "event-emission-rate", "event-outcome-drift", "event-registry-coverage",
        "event-severity-drift", "events-destructive-maintenance-audit",
        "events-historical-coverage-collapse", "events-synthetic-contamination",
        "flow-stage-json", "frontmatter-schema", "gh-orphan-detection",
        "incomplete-deploy-stage", "incomplete-idea-bodies",
        "invalid-item-flows", "lifecycle-continuity", "migration-audit",
        "missing-flow", "null-project-items",
        "offer-envelope-clobber-lost-chain", "orphan-epic-tasks", "orphan-fk",
        "orphaned-active-items", "orphaned-done-items", "orphaned-ephemeral",
        "orphaned-gh-issues", "orphaned-project-items", "orphaned-runs",
        "path-claim-coordination-rationale", "path-claim-hard-blocks",
        "path-claim-owner-kind", "path-claim-register-rejected-with-deps",
        "path-integrity", "premature-done", "preview-occupancy-stale",
        "project-checkout-mapping", "project-fk-integrity",
        "project-flow-migration-apply-coverage", "project-json-validity",
        "project-verification-configured", "projects-ci-workflow-configured",
        "projects-config-alignment", "projects-without-flows",
        "qa-runs-mutated", "reflection-capture-persist-failed",
        "reflection-capture-unhandled", "retired-schema-resurrection",
        "reviewed-implementation-epics-no-sim",
        "routed-ownership-live-frame-no-defense",
        "routed-ownership-non-terminal-release-still-schedulable",
        "run-item-status-consistency", "run-qa-unsatisfied", "schema-drift",
        "session-cwd-binding", "session-lane-mismatch",
        "session-pre-implementing-activity", "shepherd-lifecycle",
        "shepherd-spec-integrity", "skip-polish-manual-hop",
        "smoke-artifact-orphan", "smoke-failure-stale", "stale-body",
        "stale-reclaim-collision", "stale-remote-branches", "stale-runs",
        "stale-session-reclaimer-alive", "stale-sessions",
        "status-consistency", "stop-hook-chain-end-deferred",
        "synthetic-event-contamination", "title-length", "undeployed-done",
        "validation-no-qa-reqs", "work-claim-status-mismatch",
        "wrong-repo-issues", "zombie-ephemeral-envs",
    )),
    (_SRC, (
        "architecture-cross-cutting-entrypoint", "architecture-forbidden-edge",
        "architecture-model-doc-drift", "architecture-scan-error",
        "architecture-unclassified-path", "branch-divergence",
        "config-validation", "cross-project-commits", "file-line-limit",
        "flow-workflow-exists", "gate-liveness", "main-checkout",
        "orphaned-stashes", "orphaned-temp-files", "path-claim-symlink-coverage",
        "path-confabulation", "size-bloat", "strategy-render-staleness",
        "stray-db", "stray-project-files", "test-command-validity",
        "uncaptured-discoveries", "worktree-health",
    )),
    (_SELF, (
        "agent-canonical-drift", "agent-consistency", "api-vocabulary-drift",
        "apply-patch-deny-smoke", "apply-patch-observe-smoke",
        "approval-contract-drift", "arch-consistency", "atlas-integrity",
        "board-emoji-universality", "browser-substrate", "claudemd-drift",
        "cli-help-handler-present", "codex-agent-adapter-drift",
        "codex-hook-doc-drift", "codex-hook-floor", "codex-hook-matchers",
        "codex-subagent-surface-truth", "doc-drift", "doc-health",
        "event-callsite-registry-sync", "event-catalog-drift",
        "event-outcome-enum-coverage", "events-app-state-reads",
        "executor-canonicalization", "fallback-registry-coherence",
        "field-note-coherence", "harness-substrate-drift",
        "heading-casing-canon", "historical-yok-n-cruft", "hook-executability",
        "install-bundle-drift", "item-ref-construction", "obsoleted-terms",
        "packet-tier-completeness", "path-claim-bash-guard",
        "platform-namespace-boundary", "progressive-disclosure-direction",
        "prompt-command-consistency", "prompt-doctrine-consistency",
        "reflection-capture-hook-coverage", "schema-script-sync", "self-test",
        "server-checkout-independence", "session-startup-hook",
        "skill-recipe-execution", "substrate-project-leak",
        "terminal-recipe-residue", "tier-cli-shape-bleed",
        "tier-module-path-resolution", "tier-schema-bleed",
        "workspace-anchored-writer-authority",
    )),
    (_EXT, (
        "project-deploy-flows", "project-gh-auth", "project-gh-secrets",
        "project-lookup", "project-repo-exists",
    )),
    (_EXT_SRC, ("project-worktrees",)),
    (_MIGRATION, ("oneshot-migration-coverage", "stranded-migration-module")),
    (_EXT_HEALTH, ("project-health",)),
    (_EXT_VPS, ("project-vps-reachable",)),
)


DECLARATIONS: Dict[str, CheckApplicability] = {
    slug: shape for shape, slugs in _SHAPES for slug in slugs
}


def applicability_for(slug: str) -> CheckApplicability:
    """The declared applicability for *slug*.

    An undeclared slug falls back to the universal shape so a newly landed
    check still runs; ``HC-doctor-applicability-declaration`` reports the
    missing declaration rather than letting the fallback stand unnoticed.
    """
    return DECLARATIONS.get(slug, UNIVERSAL)


def undeclared_slugs(slugs) -> List[str]:
    """Registered slugs with no entry in :data:`DECLARATIONS`."""
    return sorted(slug for slug in slugs if slug not in DECLARATIONS)


__all__ = ["DECLARATIONS", "applicability_for", "undeclared_slugs"]
