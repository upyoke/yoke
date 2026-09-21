"""Reachable-recovery text when a QA snapshot cannot be reused."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.qa_plan_management import _placeholder
from yoke_core.domain.qa_requirement_target_rebind import (
    declaration_correction_applies,
    different_target_reuse_recovery,
)
from yoke_core.domain.refusal_recovery import compose_refusal


def requirement_verdict_and_runs(
    conn: Any | None, requirement_id: int
) -> tuple[str, bool]:
    """Latest verdict and whether any run row exists for this requirement."""
    if conn is None:
        return "", False
    marker = _placeholder(conn)
    row = conn.execute(
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id="
        f"{marker} ORDER BY created_at DESC,id DESC LIMIT 1",
        (int(requirement_id),),
    ).fetchone()
    verdict = (
        str((row["verdict"] if hasattr(row, "keys") else row[0]) or "")
        if row
        else ""
    )
    runs = conn.execute(
        f"SELECT 1 FROM qa_runs WHERE qa_requirement_id={marker} LIMIT 1",
        (int(requirement_id),),
    ).fetchone()
    return verdict, runs is not None


def different_target_refusal(
    *,
    subject: str,
    requirement_id: int,
    stored_digest: str,
    expected_digest: str,
    latest_verdict: str,
    has_runs: bool,
    item_bound: bool,
    state_known: bool = True,
    stored_target: Mapping[str, Any] | None = None,
    current_target: Mapping[str, Any] | None = None,
) -> str:
    """Refusal when a live snapshot is bound to a different execution target."""
    rebind_ok = declaration_correction_applies(stored_target, current_target)
    unavailable = [
        f"rematerialize — cannot replace requirement {requirement_id} while "
        "it remains the live snapshot holding the previous digest",
    ]
    if latest_verdict == "pass":
        unavailable.append(
            f"retract — refused because requirement {requirement_id} already "
            "recorded a passing verdict"
        )
    if not rebind_ok:
        if item_bound:
            unavailable.append(
                "start a fresh deployment/plan execution — this call is item "
                "materialization; workers must not create a deployment run"
            )
        else:
            unavailable.append(
                "start a fresh deployment/plan execution — steering owns the run; "
                "this caller cannot create one"
            )
    retract_ok = (not rebind_ok) and state_known and latest_verdict != "pass"
    if rebind_ok:
        recovery: str | None = different_target_reuse_recovery(
            stored_target=stored_target or {},
            current_target=current_target or {},
            requirement_id=requirement_id,
        )
        escalate_to: str | None = None
    elif retract_ok:
        recovery = (
            "retract the mis-scoped attachment "
            "(yoke qa item-plan retract) then rematerialize"
        )
        escalate_to = None
    else:
        recovery = None
        escalate_to = (
            "the operator to retire or supersede requirement "
            f"{requirement_id} deliberately, then rematerialize a "
            "snapshot for the current target"
        )
    return compose_refusal(
        f"{subject} has QA requirement {requirement_id} bound to a "
        "different execution target",
        evaluated=(
            f"stored digest {stored_digest or 'none'} vs current "
            f"{expected_digest}; latest verdict {latest_verdict or 'none'}; "
            f"{'has run evidence' if has_runs else 'no run rows'}"
        ),
        unavailable=unavailable,
        recovery=recovery,
        escalate_to=escalate_to,
    )


__all__ = ["different_target_refusal", "requirement_verdict_and_runs"]
