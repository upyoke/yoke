"""Preflight gate evaluation for the advance implementation entry.

Owns the pre-worktree refusal gates run before an item advances into
``implementing``: upstream hard-block dependencies, acceptance-criteria
presence, File Budget, and path-claim spec coverage. Kept separate from
the orchestrator module so it stays within the authored-file line cap.

Each gate reads the control-plane DB. The reads route through the
transport-aware ``call_dispatcher`` facade (registered
``advance.preflight.*`` internal functions) so the evaluation works over
an https control plane as well as an in-process local Postgres
connection. The gate ordering, short-circuit behavior, and operator-facing
narratives are constructed here client-side, unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.item_ref import format_item_ref

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher


def _relay_gate(
    function_id: str, item_id: int, payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Evaluate one gate server-side through the transport-aware relay.

    Raises when the relay refuses so an unevaluable gate fails closed —
    a refusal gate must never be treated as passing.
    """
    response = call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload=payload or {},
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = (
            response.error.message if response.error else "gate evaluation failed"
        )
        raise RuntimeError(f"{function_id} failed ({code}): {message}")
    return response.result or {}


def _run_preflight_gates(item_id: int, *, force: bool) -> Tuple[bool, str]:
    """Hard-block dep + AC presence + spec coverage. Returns (ok, narrative)."""
    if force:
        return True, ""

    blockers = _relay_gate(
        "advance.preflight.hard_blocks", item_id,
        {"gate_filter": "activation"},
    ).get("blockers") or []
    if blockers:
        return False, "Blocked by dependencies:\n  " + "\n  ".join(blockers)

    ac = _relay_gate("advance.preflight.ac_presence", item_id)
    title = ac.get("title")
    canonical = int(ac.get("canonical") or 0)
    # No-conn fallback: this gate path must not open a bare local connect
    # (https control planes relay gate reads server-side). Prefer an
    # item_ref the relay already returned; otherwise format from the id.
    item_ref = (
        ac.get("item_ref")
        or format_item_ref(None, None, None, item_id=int(item_id))
    )
    if title is None:
        return False, f"{item_ref} not found in DB."
    if canonical <= 0:
        return False, (
            f"{item_ref} has no acceptance criteria. Add "
            f"`## Acceptance Criteria` with `- [ ] AC-N: ...` checkboxes."
        )

    budget = _relay_gate("advance.preflight.file_budget", item_id)
    if budget.get("verdict") != "pass":
        return False, f"BLOCKED: {budget.get('reason')}"

    cov = _relay_gate("advance.preflight.spec_coverage", item_id)
    if cov.get("is_blocked"):
        missing = cov.get("missing_paths") or []
        cov_ref = (
            cov.get("item_ref")
            or item_ref
        )
        return False, (
            f"BLOCKED: {cov_ref} File Budget lists "
            f"{len(missing)} path(s) not covered by any active "
            f"path_claim.\nMissing: " + ", ".join(missing)
        )
    return True, ""


__all__ = ["_run_preflight_gates"]
