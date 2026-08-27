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
There is deliberately no self-project shape here. A check that only
describes the project owning this installation — its agent prompts, skills,
docs, harness adapters, code doctrine — belongs in that project's own
``.yoke/doctor/`` folder, where it carries its declaration on its own row.
The engine roster is what is true of any project Yoke manages.
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
    RUNTIME_LOCAL,
    UNIVERSAL,
)


_DB = UNIVERSAL
_LOCAL = CheckApplicability(runtimes=frozenset({RUNTIME_LOCAL}))
_SRC = CheckApplicability(requires_source_checkout=True)
_EXT = CheckApplicability(project_scope=PROJECT_SCOPE_EXTERNAL)
_EXT_SRC = CheckApplicability(
    project_scope=PROJECT_SCOPE_EXTERNAL,
    requires_source_checkout=True,
)
_MIGRATION = CheckApplicability(
    requires_source_checkout=True,
    required_capabilities=("migration_model",),
)
_EXT_HEALTH = CheckApplicability(
    project_scope=PROJECT_SCOPE_EXTERNAL,
    required_capabilities=("health-endpoint",),
)
_EXT_VPS = CheckApplicability(
    project_scope=PROJECT_SCOPE_EXTERNAL,
    required_capabilities=("vps-ssh",),
)


_SHAPES = (
    (
        _DB,
        (
            "architecture-cross-cutting-entrypoint",
            "architecture-forbidden-edge",
            "architecture-impact-declaration",
            "architecture-scan-error",
            "architecture-unclassified-path",
            "backlog-hygiene",
            "backlog-quality",
            "blocked-flag-consistency",
            "blocked-items",
            "blocked-status-drift",
            "branch-protection-required-check",
            "cancelled-blocker-dependencies",
            "claim-boundary-audit",
            "coordination-claims-stale-or-orphan",
            "coordination-claims-unmerged-source",
            "deferred-items",
            "delegated-sync",
            "dependency-drift",
            "deploy-stage-integrity",
            "dispatch-chain",
            "duplicate-projects",
            "empty-task-worktree",
            "epic-task-scope-state",
            "epic-task-worktree",
            "epic-task-worktree-backfill",
            "epic-validation",
            "event-emission-rate",
            "event-outcome-drift",
            "event-registry-coverage",
            "event-severity-drift",
            "events-destructive-maintenance-audit",
            "events-historical-coverage-collapse",
            "events-synthetic-contamination",
            "flow-stage-environment-input",
            "flow-stage-json",
            "frontmatter-schema",
            "gh-orphan-detection",
            "incomplete-deploy-stage",
            "incomplete-idea-bodies",
            "invalid-item-flows",
            "lifecycle-continuity",
            "merge-queue-binding",
            "migration-audit",
            "missing-flow",
            "null-project-items",
            "offer-envelope-clobber-lost-chain",
            "organization-settings",
            "orphan-epic-tasks",
            "orphan-fk",
            "orphaned-active-items",
            "orphaned-done-items",
            "orphaned-ephemeral",
            "orphaned-gh-issues",
            "orphaned-project-items",
            "orphaned-runs",
            "path-claim-coordination-rationale",
            "path-claim-hard-blocks",
            "path-claim-owner-kind",
            "path-claim-register-rejected-with-deps",
            "path-integrity",
            "premature-done",
            "preview-occupancy-stale",
            "project-checkout-mapping",
            "project-fk-integrity",
            "project-json-validity",
            "project-verification-configured",
            "projects-ci-workflow-configured",
            "projects-config-alignment",
            "projects-without-flows",
            "qa-runs-mutated",
            "reflection-capture-persist-failed",
            "reflection-capture-unhandled",
            "retired-schema-resurrection",
            "reviewed-implementation-epics-no-sim",
            "routed-ownership-live-frame-no-defense",
            "routed-ownership-non-terminal-release-still-schedulable",
            "run-item-status-consistency",
            "run-qa-unsatisfied",
            "schema-drift",
            "session-cwd-binding",
            "session-lane-mismatch",
            "session-pre-implementing-activity",
            "shepherd-lifecycle",
            "shepherd-spec-integrity",
            "skip-polish-manual-hop",
            "smoke-artifact-orphan",
            "smoke-failure-stale",
            "stale-body",
            "stale-reclaim-collision",
            "stale-remote-branches",
            "stale-runs",
            "stale-session-reclaimer-alive",
            "stale-sessions",
            "status-consistency",
            "stop-hook-chain-end-deferred",
            "synthetic-event-contamination",
            "title-length",
            "undeployed-done",
            "validation-no-qa-reqs",
            "work-claim-status-mismatch",
            "wrong-repo-issues",
            "zombie-ephemeral-envs",
        ),
    ),
    (
        _SRC,
        (
            "architecture-model-doc-drift",
            "branch-divergence",
            "config-validation",
            "cross-project-commits",
            "file-line-limit",
            "flow-workflow-exists",
            "gate-liveness",
            "launcher-authority",
            "main-checkout",
            "orphaned-stashes",
            "orphaned-temp-files",
            "path-claim-symlink-coverage",
            "path-confabulation",
            "project-hook-config-validity",
            "size-bloat",
            "strategy-render-staleness",
            "stray-db",
            "stray-project-files",
            "test-command-validity",
            "uncaptured-discoveries",
            "worktree-health",
        ),
    ),
    (_LOCAL, ("session-relay", "session-relay-orphans")),
    (
        _EXT,
        (
            "project-deploy-flows",
            "project-gh-auth",
            "project-gh-secrets",
            "project-lookup",
            "project-repo-exists",
        ),
    ),
    (_EXT_SRC, ("project-worktrees",)),
    (
        _MIGRATION,
        (
            "oneshot-migration-coverage",
            "pending-migrations",
            "project-migration-ledger-contract",
        ),
    ),
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


def source_checkout_slugs() -> frozenset[str]:
    """Slugs whose applicability requires a machine-local source checkout."""
    return frozenset(
        slug for slug, shape in DECLARATIONS.items() if shape.requires_source_checkout
    )


def local_runtime_slugs() -> frozenset[str]:
    """Slugs that must execute on the operator's own machine."""
    return frozenset(
        slug for slug, shape in DECLARATIONS.items()
        if shape.runtimes == _LOCAL.runtimes
    )


__all__ = [
    "DECLARATIONS",
    "applicability_for",
    "local_runtime_slugs",
    "source_checkout_slugs",
    "undeclared_slugs",
]
