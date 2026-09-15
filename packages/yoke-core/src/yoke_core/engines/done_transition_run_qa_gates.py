"""Both QA authorities a deployment run answers to before its item is done.

A run carries QA evidence in two shapes, and an item is done only when
both hold:

* the legacy ``deployment_run_qa`` projection, which schema-1 flow checks
  record against, and
* the scoped per-stage acceptance the richer flow definition pins, which
  settles through ``qa_requirements`` / ``qa_runs`` and deliberately
  writes no ``deployment_run_qa`` row at all.

Neither is a superset of the other, so consulting one alone lets the
other pass unread: a legacy flow has no scoped stages, and a scoped flow
has no legacy rows. Both reads relay, so the gate runs over an https
control plane as well as a local Postgres connection, and an
unavailable read raises rather than reporting a clear gate.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher


def _relay_read(
    function_id: str, target: TargetRef, payload: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    resp = call_dispatcher(
        function_id=function_id, target=target, payload=payload or {}
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"{function_id} read failed: {message}")
    return resp.result or {}


def _legacy_blocking(run_id: str) -> List[str]:
    """Unsatisfied schema-1 flow checks recorded on the run."""
    return list(
        _relay_read(
            "done_transition.run_blocking_qa",
            TargetRef(kind="global"),
            {"run_id": run_id},
        ).get("blocking", [])
    )


def _scoped_blocking(item_id: int, run_id: str) -> List[str]:
    """Unsatisfied scoped stage verdicts this item still owes in the run."""
    return list(
        _relay_read(
            "done_transition.run_stage_qa_acceptance",
            TargetRef(kind="item", item_id=int(item_id)),
            {"run_id": run_id},
        ).get("blocking", [])
    )


def check_run_qa_gates(item_id: int, run_id: str) -> bool:
    """Report and block when either QA authority is unsatisfied.

    Returns ``True`` when the item must not proceed to done.
    """
    if not run_id:
        return False
    blocking = _legacy_blocking(run_id) + _scoped_blocking(item_id, run_id)
    if not blocking:
        return False
    print("\n=== Deployment QA guard ===")
    print(
        f"Blocked: Deployment run '{run_id}' has QA obligations that are "
        "unsatisfied for this item:"
    )
    for check in blocking:
        print(f"  - {check}")
    print(
        "\nSupply each stage's evidence and verdict (or an authorized waiver) "
        "before transitioning to done."
    )
    return True


__all__ = ["check_run_qa_gates"]
