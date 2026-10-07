"""Named allowances for :mod:`yoke_core.domain.lint_project_name_literal`.

Each allowance names one ``(relpath, subject)`` site and why its literal is
not a project-name branch. ``pending`` sites ARE project-name branches whose
replacement is in flight: the doctor check reports them as WARN rather than
PASS, so they stay visible until they are gone. An allowance that no longer
matches any hit is stale and fails the check, so the list only shrinks with
the code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Tuple

from yoke_core.domain.lint_project_name_literal import ProjectLiteralHit


@dataclass(frozen=True)
class Allowance:
    relpath: str
    subject: str
    reason: str
    pending: bool = False


ALLOWANCES: Tuple[Allowance, ...] = (
    Allowance(
        "packages/yoke-contracts/src/yoke_contracts/playwright_cache.py",
        "YOKE_BROWSER_CACHE_PROJECT",
        "machine-wide Browser QA cache namespace, not a registered project",
    ),
    Allowance(
        "packages/yoke-contracts/src/yoke_contracts/machine_config/schema_example.py",
        "app_slug",
        "GitHub App slug in a documented configuration example",
    ),
    Allowance(
        "packages/yoke-core/src/yoke_core/domain/item_landings_reconstruct.py",
        "YOKE_PROJECT_SLUG",
        "read only by a permanent migration that reconstructs this "
        "repository's own historical landings",
    ),
    Allowance(
        "packages/yoke-core/src/yoke_core/domain/lint_yok_n_cruft_status.py",
        "_PROJECT_SLUG",
        "backs the Yoke repository's own historical-ref check",
    ),
    Allowance(
        "runtime/api/tools/require_platform_consumer_compatibility.py",
        "CONSUMER_PROJECT",
        "release-train gate naming the external consumer repository it builds",
    ),
    Allowance(
        "runtime/api/domain/standalone_merge_simulation_support.py",
        "project",
        "test scaffolding imported only by tests",
    ),
    Allowance(
        "runtime/api/cli/onboard_wizard_golden_support.py",
        "slug",
        "golden test scaffolding imported only by tests",
    ),
    Allowance(
        "runtime/api/tools/preflight_fleet_migrations.py",
        "RECEIPT_PROJECT",
        "fleet receipts move to the declared migration model's owning project",
        pending=True,
    ),
    Allowance(
        "runtime/api/tools/preflight_fleet_migrations.py",
        "project",
        "fleet receipts move to the declared migration model's owning project",
        pending=True,
    ),
    Allowance(
        "runtime/api/tools/require_fleet_migration_preflight.py",
        "project",
        "fleet receipts move to the declared migration model's owning project",
        pending=True,
    ),
)


def classify(
    hits: Iterable[ProjectLiteralHit],
    allowances: Tuple[Allowance, ...] = ALLOWANCES,
) -> Tuple[List[ProjectLiteralHit], List[ProjectLiteralHit], List[Allowance]]:
    """Split *hits* into ``(violations, pending, stale_allowances)``.

    Hits matching a permanent allowance are dropped; hits matching a pending
    one are returned separately; allowances matching no hit are stale.
    """
    by_key = {(a.relpath, a.subject): a for a in allowances}
    used = set()
    violations: List[ProjectLiteralHit] = []
    pending: List[ProjectLiteralHit] = []
    for hit in hits:
        allowance = by_key.get((hit.relpath, hit.subject))
        if allowance is None:
            violations.append(hit)
            continue
        used.add((allowance.relpath, allowance.subject))
        if allowance.pending:
            pending.append(hit)
    stale = [a for a in allowances if (a.relpath, a.subject) not in used]
    return violations, pending, stale


__all__ = ["ALLOWANCES", "Allowance", "classify"]
