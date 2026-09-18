"""Repairing an item from files the repairing host may not hold.

Both readiness repairs rewrite an item from what the file-reading checks
saw: the stale-count repair replaces recorded line counts, and the
claim-coverage repair widens or narrows a path claim to match the File
Budget. On the hosted control plane neither host has the tree those
checks read, so both arrive here through the observation handoff and
both need the same two things from it.

**Live counts without a checkout.** A stale-count repair needs each
path's real length. With a checkout it stats the file. Without one it
takes the number the observing machine reported, which is sound only
because that reading has already been admitted as a finding about a path
this item's File Budget lists, and because the repair is re-verified
afterwards: a wrong number simply fails the same check again on the next
pass rather than settling in.

**A re-run that can actually re-verify.** A repair whose result cannot be
checked is worse than one that never ran, so the re-run takes the
handoff too. The two journeys differ in what that costs. Claim coverage
does not touch the spec or the tree, so the answer that drove the repair
is still bound afterwards and is reused directly. The stale-count repair
rewrites the spec, which by design breaks the binding of every answer
collected before it — so its re-run comes back unperformed, and the
caller holding the checkout is asked for a fresh reading it can be
verified against.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

NO_CHECKOUT_TO_REPAIR_AGAINST = (
    "no checkout for this item's project on this host, and no reading from "
    "a machine that has one; repair needs the project's files. Re-run from "
    "a machine whose checkout for that project is registered."
)
NARROW_NEEDS_CHECKOUT = "narrow_boundary_checkout_missing"


def rerun_readiness(
    item_id: int, observations: Optional[Dict[str, Any]] = None,
) -> Any:
    """Re-run every readiness check after a repair, through the handoff."""
    from yoke_core.domain.idea_readiness_check import run_all_checks
    from yoke_core.domain.schema_common import _connect_raw

    conn = _connect_raw()
    try:
        return run_all_checks(conn, item_id, observations)
    finally:
        conn.close()


def observed_line_count(context: Dict[str, Any]) -> Optional[int]:
    """The length the observing machine read, when it reported a usable one."""
    raw = context.get("actual")
    try:
        actual = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return actual if actual >= 0 else None


def live_line_count(
    repo_root: Optional[Path], rel: str, context: Dict[str, Any],
) -> Optional[int]:
    """This path's real length, from the tree here or the machine that has it."""
    if repo_root is None:
        return observed_line_count(context)
    candidate = repo_root / rel
    if not candidate.exists():
        return None
    return sum(1 for _ in candidate.open(encoding="utf-8"))


def paths_from_issues(issues: List[Dict[str, Any]], code: str) -> List[str]:
    """Every distinct ``context.path`` reported under one issue code.

    Each path becomes a path-claim amendment, so these must only ever be
    issues that survived admission — a code the file-reading checks can
    emit, naming a path this item's File Budget lists.
    """
    seen: Set[str] = set()
    out: List[str] = []
    for issue in issues:
        if str(issue.get("code") or "") != code:
            continue
        path = str((issue.get("context") or {}).get("path") or "")
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def narrow_refusal_without_checkout(
    repo_path: Optional[str], drop_paths: List[str],
) -> Optional[Dict[str, Any]]:
    """Refuse a narrow no host can prove, before anything is mutated.

    Narrowing drops paths from a claim, and the boundary proof that no
    committed work is orphaned reads the worktree. There is no handoff
    for it — the observing machine is asked for readiness findings, not
    for a claim boundary — so a host without the tree has to refuse, and
    it has to refuse before the paired widen has run.
    """
    if repo_path:
        return None
    return {"reason": NARROW_NEEDS_CHECKOUT, "drop_paths": list(drop_paths)}


def repair_verifiable(
    repo_root: Optional[Path], observations: Optional[Dict[str, Any]],
) -> bool:
    """Can this repair's result be checked once it is applied?"""
    return repo_root is not None or observations is not None


__all__ = [
    "NARROW_NEEDS_CHECKOUT",
    "NO_CHECKOUT_TO_REPAIR_AGAINST",
    "live_line_count",
    "narrow_refusal_without_checkout",
    "observed_line_count",
    "paths_from_issues",
    "repair_verifiable",
    "rerun_readiness",
]
