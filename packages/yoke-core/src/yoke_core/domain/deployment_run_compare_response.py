"""Read one repository comparison response, or refuse to read it at all.

Every field here is load-bearing, and every gap in one is a reason to answer
"unknown" rather than "empty". A status this reader does not recognize, an
absent commit total, and a missing listing each mean the comparison did not
say what the range holds; treating any of them as a default would let a
malformed body authorize a completion or record an empty release.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.deployment_run_carried_work_source import (
    RELATION_AHEAD,
    RELATION_DIVERGED,
    CarriedWorkSourceUnavailable,
)


# ``status`` describes the head relative to the base, and the base is the
# older lineage: a head carrying it is ahead of it, or identical to it.
CONTAINING_STATUSES = frozenset({"ahead", "identical"})
DIVERGED_STATUSES = frozenset({"behind", "diverged"})


def relation(status: str) -> str:
    if status in CONTAINING_STATUSES:
        return RELATION_AHEAD
    return RELATION_DIVERGED


def require_status(body: Mapping[str, Any]) -> str:
    status = str(body.get("status") or "").strip()
    if status not in CONTAINING_STATUSES and status not in DIVERGED_STATUSES:
        raise CarriedWorkSourceUnavailable(
            "repository_provider_comparison_incomplete",
            f"The comparison reported status {status!r}, which this reader "
            "does not recognize; retry once the provider is healthy.",
        )
    return status


def require_total(body: Mapping[str, Any]) -> int:
    total = body.get("total_commits")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise CarriedWorkSourceUnavailable(
            "repository_provider_comparison_incomplete",
            "The comparison omitted its commit total; retry once the provider "
            "is healthy.",
        )
    return total


def require_commits(body: Mapping[str, Any]) -> list[Any]:
    commits = body.get("commits")
    if not isinstance(commits, list):
        raise CarriedWorkSourceUnavailable(
            "repository_provider_comparison_incomplete",
            "The comparison omitted its commit listing; retry once the "
            "provider is healthy.",
        )
    return commits


def is_hex(value: str) -> bool:
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


__all__ = [
    "CONTAINING_STATUSES",
    "DIVERGED_STATUSES",
    "is_hex",
    "relation",
    "require_commits",
    "require_status",
    "require_total",
]
