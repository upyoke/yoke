"""Backlog DB-mutation gate dispatch (governed DB-mutation contract §7) — composes the joint /
evidence / polish gates and the prose-vs-claim consistency check
used by the canonical status-write path. Each helper returns the
canonical `{"success": False, ...}` failure payload or `None` on pass.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect


# Statuses where the joint gate has already had its chance to run.  When
# the item has progressed past these, declaration grandfathering applies
# per §11.1 and we do NOT re-evaluate the joint gate on lateral writes.
_DB_MUTATION_GATE_TARGETS = {
    "refining-idea": "joint",
    "reviewing-implementation": "evidence",
    "implemented": "polish",
}

# Targets that trigger a prose-vs-claim consistency check.
# Distinct from `_DB_MUTATION_GATE_TARGETS` because the prose check fires
# on more transitions than the heavy gates: refine completes at
# ``refined-idea`` / ``planned`` and any of those advances should block
# when the spec/body declares governed DB work but the stored profile is
# still ``state="none"``.  Heavy-gate targets are also included so the
# joint/evidence/polish dispatch composes the prose check alongside
# their existing checks.
_PROSE_CHECK_TARGETS = frozenset({
    "refining-idea",
    "refined-idea",
    "planned",
    "reviewing-implementation",
    "implemented",
})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _profile_declares_mutation(conn: Any, item_id: int) -> bool:
    """Return True when the item's ``db_mutation_profile.state`` is ``declared``.

    Negative claims (``state="none"``) stay unfrozen — the auto-stamp
    side effect on the joint gate only engages when the ticket
    actually declares a governed DB mutation.
    """
    row = conn.execute(
        f"SELECT db_mutation_profile FROM items WHERE id = {_p(conn)}",
        (item_id,),
    ).fetchone()
    if row is None:
        return False
    raw = row["db_mutation_profile"] if hasattr(row, "keys") else row[0]
    if not raw:
        return False
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    return parsed.get("state") == "declared"


def _run_prose_vs_claim_check(
    *,
    item_id: int,
    db_path: str,
) -> Optional[dict]:
    """Run the prose-vs-claim consistency check.

    Returns the canonical failure payload when the spec/body names
    governed DB mutation but the stored ``db_mutation_profile`` is still
    ``state="none"``.  Returns ``None`` when the prose is clean, the
    claim is already declared, or the check is unavailable
    (import/schema issue).
    """
    try:
        from yoke_core.domain import db_claim_prose_check
    except ImportError:
        return None
    conn = connect(db_path)
    try:
        outcome = db_claim_prose_check.check_item(item_id, conn=conn)
    except db_backend.operational_error_types(conn) as exc:
        # Minimal legacy schemas may lack the columns the check reads.
        # The contract has nothing to enforce in that case.
        if "no such column" in str(exc) or "no such table" in str(exc):
            return None
        raise
    finally:
        conn.close()
    if not outcome.blocks:
        return None
    triggers = ", ".join(f"'{t}'" for t in outcome.triggers[:5])
    if len(outcome.triggers) > 5:
        triggers += ", ..."
    return {
        "success": False,
        "error": (
            f"prose-vs-claim mismatch on YOK-{item_id}: stored "
            "db_mutation_profile is state='none' but spec/body declares "
            f"governed DB work ({triggers}).  {outcome.recovery}"
        ),
        "error_code": "GATE_DB_CLAIM_PROSE_MISMATCH",
    }


def _run_db_mutation_gate(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
) -> Optional[dict]:
    """Dispatch to the appropriate governed-DB-mutation gate per target.

    Returns ``None`` when the target is not a gated transition or when
    every gate (heavy + prose) passes (and any post-gate side effects
    have run).  Returns the canonical failure payload when any gate
    blocks; the first failure wins so the operator-facing error is
    attributable to a single rule.
    """
    if target_status in _PROSE_CHECK_TARGETS:
        prose_result = _run_prose_vs_claim_check(
            item_id=item_id, db_path=db_path,
        )
        if prose_result is not None:
            return prose_result

    gate_kind = _DB_MUTATION_GATE_TARGETS.get(target_status)
    if gate_kind is None:
        return None

    try:
        from yoke_core.domain import db_mutation_gate
    except ImportError:
        return None

    conn = connect(db_path)
    try:
        if gate_kind == "joint":
            outcome = db_mutation_gate.check_idea_to_refining_idea_gate(
                item_id, conn=conn,
            )
        elif gate_kind == "evidence":
            outcome = db_mutation_gate.check_implementing_to_reviewing_implementation_gate(
                item_id, conn=conn,
            )
        elif gate_kind == "polish":
            outcome = db_mutation_gate.check_polishing_implementation_to_implemented_gate(
                item_id, conn=conn,
            )
        else:  # pragma: no cover - exhaustive
            return None

        if not outcome.passed:
            error_codes = {
                "joint": "GATE_DB_MUTATION_JOINT",
                "evidence": "GATE_DB_MUTATION_EVIDENCE",
                "polish": "GATE_DB_MUTATION_POLISH",
            }
            return {
                "success": False,
                "error": "\n".join(outcome.errors) or "DB-mutation gate failed",
                "error_code": error_codes[gate_kind],
            }

        # Joint-gate side effect: stamp frozen_at only when the
        # profile declares a governed mutation. Negative claims
        # (state="none") stay mutable — they remain editable via the
        # unified DB-claim amendment workflow through every
        # pre-implementation state. The workflow is the sole writer of
        # frozen_at for declared claims going forward, but the joint
        # gate also stamps on pass so any surviving direct-to-refining
        # path still engages the downstream authored-field
        # immutability invariants for pre_merge_safe attestations.
        if gate_kind == "joint" and _profile_declares_mutation(conn, item_id):
            db_mutation_gate.stamp_attestation_frozen_at(
                item_id,
                conn=conn,
                extra_escalations=outcome.escalations or None,
            )
    except db_backend.operational_error_types(conn) as exc:
        # Tests that stage a minimal legacy schema may lack the
        # project_capabilities/migration_audit columns the gate inspects.
        # In that case the contract has nothing to enforce — opt out.
        if "no such column" in str(exc) or "no such table" in str(exc):
            return None
        raise
    finally:
        conn.close()

    return None


__all__ = [
    "_DB_MUTATION_GATE_TARGETS",
    "_PROSE_CHECK_TARGETS",
    "_profile_declares_mutation",
    "_run_prose_vs_claim_check",
    "_run_db_mutation_gate",
]
