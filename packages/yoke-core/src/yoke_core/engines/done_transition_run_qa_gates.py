"""Require the item's pinned stage QA acceptance before completion."""

from __future__ import annotations

from yoke_core.domain.public_item_target import public_item_target

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


def _scoped_blocking(item_id: int, run_id: str) -> List[str]:
    """Unsatisfied scoped stage verdicts this item still owes in the run."""
    return list(
        _relay_read(
            "done_transition.run_stage_qa_acceptance",
            public_item_target(item_id),
            {"run_id": run_id},
        ).get("blocking", [])
    )


def check_run_qa_gates(item_id: int, run_id: str) -> bool:
    """Report and block when pinned stage QA is unsatisfied.

    Returns ``True`` when the item must not proceed to done.
    """
    if not run_id:
        return False
    blocking = _scoped_blocking(item_id, run_id)
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
