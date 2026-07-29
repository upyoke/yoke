"""Preflight gate evaluation for the advance implementation entry.

Owns the pre-worktree refusal gates run before an item advances into
``implementing``: upstream hard-block dependencies, acceptance-criteria
presence, File Budget, and path-claim spec coverage. Kept separate from
the orchestrator module so it stays within the authored-file line cap.
"""

from __future__ import annotations

from typing import Tuple

from yoke_core.domain import db_helpers


def _run_preflight_gates(item_id: int, *, force: bool) -> Tuple[bool, str]:
    """Hard-block dep + AC presence + spec coverage. Returns (ok, narrative)."""
    if force:
        return True, ""
    from yoke_core.domain import check_hard_blocks
    from yoke_core.domain import check_ac_presence
    from yoke_core.domain import file_budget_required_gate
    from yoke_core.domain import path_claim_spec_coverage_gate

    blockers = check_hard_blocks.evaluate_blockers(
        item_id, gate_filter="activation",
    )
    if blockers:
        return False, "Blocked by dependencies:\n  " + "\n  ".join(blockers)
    canonical, _unlabeled, title = check_ac_presence.evaluate_item(item_id)
    if title is None:
        return False, f"YOK-{item_id} not found in DB."
    if canonical <= 0:
        return False, (
            f"YOK-{item_id} has no acceptance criteria. Add "
            f"`## Acceptance Criteria` with `- [ ] AC-N: ...` checkboxes."
        )
    with db_helpers.connect() as conn:
        budget = file_budget_required_gate.evaluate(conn, item_id)
    if budget["verdict"] != "pass":
        return False, f"BLOCKED: {budget['reason']}"
    cov = path_claim_spec_coverage_gate.evaluate(item_id)
    if cov.is_blocked:
        return False, (
            f"BLOCKED: YOK-{item_id} File Budget lists "
            f"{len(cov.missing_paths)} path(s) not covered by any active "
            f"path_claim.\nMissing: " + ", ".join(cov.missing_paths)
        )
    return True, ""


__all__ = ["_run_preflight_gates"]
