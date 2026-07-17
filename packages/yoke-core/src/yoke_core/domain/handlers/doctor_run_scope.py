"""Scope filters for the Doctor function-call handler."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


SOURCE_TREE_HEALTH_CHECK_SLUGS = frozenset({
    "atlas-integrity",
    "agent-canonical-drift",
    "workspace-anchored-writer-authority",
    "field-note-coherence",
    "harness-substrate-drift",
    "codex-hook-matchers",
    "codex-hook-doc-drift",
    "path-claim-bash-guard",
    "event-outcome-enum-coverage",
    "server-checkout-independence",
    "installer-live-tui-import-boundary",
    "platform-namespace-boundary",
})

PROJECT_SAFE_QUICK_HEALTH_CHECK_SLUGS = frozenset({
    "project-lookup",
    "project-gh-auth",
    "project-deploy-flows",
    "projects-ci-workflow-configured",
})


def doctor_scope_label(args: Any) -> str:
    if args.only:
        return "only"
    if args.quick:
        return "quick"
    return "full"


def validate_only_slugs(only_raw: str) -> list[str] | None:
    known = _resolve_known_slugs()
    alias_map = {"confabulation": "path-confabulation"}
    unknown: list[str] = []
    for raw in only_raw.split(","):
        token = raw.strip()
        if not token:
            continue
        bare = token[3:] if token.startswith("HC-") else token
        if token in known or bare in known or alias_map.get(bare) in known:
            continue
        unknown.append(token)
    return unknown or None


def _resolve_known_slugs() -> set[str]:
    from yoke_core.engines.doctor_registry import HEALTH_CHECKS

    known = {f"HC-{hc.slug}" for hc in HEALTH_CHECKS}
    known.update(hc.slug for hc in HEALTH_CHECKS)
    return known


def filter_source_tree_checks(
    checks: Iterable[Any],
    *,
    skip: bool,
    project_safe_quick: bool = False,
) -> list[Any]:
    selected = list(checks)
    if project_safe_quick:
        return [
            check for check in selected
            if check.slug in PROJECT_SAFE_QUICK_HEALTH_CHECK_SLUGS
        ]
    if not skip:
        return selected
    return [
        check for check in selected
        if check.slug not in SOURCE_TREE_HEALTH_CHECK_SLUGS
    ]


__all__ = [
    "doctor_scope_label",
    "PROJECT_SAFE_QUICK_HEALTH_CHECK_SLUGS",
    "SOURCE_TREE_HEALTH_CHECK_SLUGS",
    "filter_source_tree_checks",
    "validate_only_slugs",
]
