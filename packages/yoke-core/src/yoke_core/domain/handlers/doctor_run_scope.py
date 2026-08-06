"""Scope helpers for the Doctor function-call handler.

Scope is what the caller asked for (``--quick`` / ``--full`` / ``--only``).
Whether a requested check can honestly answer for a given project and
runtime is a separate question, answered by the applicability model in
:mod:`yoke_core.engines.doctor_applicability` — the runner reports anything
out of scope as not-applicable rather than filtering it out of the report.
``--only`` validation consumes the already-resolved target roster so engine
and project-local checks share one typo-rejection boundary.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


#: The checks a caller holding only project-read permission may run against
#: a project it can see. This is a *permission* boundary, not an
#: applicability one: the set is small because the actor is low-privilege,
#: not because the other checks have nothing to say.
PROJECT_SAFE_QUICK_HEALTH_CHECK_SLUGS = frozenset({
    "project-lookup",
    "project-gh-auth",
    "project-deploy-flows",
    "projects-ci-workflow-configured",
})


def project_safe_quick_checks(checks: Iterable[Any]) -> list[Any]:
    """Narrow *checks* to the project-read-permission set."""
    return [
        check for check in checks
        if check.slug in PROJECT_SAFE_QUICK_HEALTH_CHECK_SLUGS
    ]


def doctor_scope_label(args: Any) -> str:
    if args.only:
        return "only"
    if args.quick:
        return "quick"
    return "full"


def validate_only_slugs(
    only_raw: str,
    known_slugs: Iterable[str],
) -> list[str] | None:
    known = set(known_slugs)
    alias_map = {"confabulation": "path-confabulation"}
    unknown: list[str] = []
    for raw in only_raw.split(","):
        token = raw.strip()
        if not token:
            continue
        bare = token[3:] if token.startswith("HC-") else token
        if bare in known or alias_map.get(bare) in known:
            continue
        unknown.append(token)
    return unknown or None


__all__ = [
    "PROJECT_SAFE_QUICK_HEALTH_CHECK_SLUGS",
    "doctor_scope_label",
    "project_safe_quick_checks",
    "validate_only_slugs",
]
