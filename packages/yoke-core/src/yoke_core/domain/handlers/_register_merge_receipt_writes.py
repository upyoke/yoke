"""Register the internal merge-receipt document read and write.

The merge boundary holds the checkout, so it cannot open the control plane
directly when that control plane is reached over https. These two functions
carry its receipt write and read across that boundary.

They are ``adapter_status='internal'`` (merge bookkeeping glue, never an agent
CLI surface), ``ambient_session_required=False`` because a merge may run in a
subprocess that resolves no ambient harness session, and claim-free because
the merge boundary already holds the item claim and the merge lock that
authorize the merge these receipts describe.
"""

from __future__ import annotations

from yoke_core.domain.handlers import merge_receipt_writes as _writes

_MODULE = "yoke_core.domain.handlers.merge_receipt_writes"


def register(registry) -> None:
    registry.register(
        "merge_receipt.record",
        _writes.handle_record_merge_receipt,
        _writes.RecordMergeReceiptRequest,
        _writes.RecordMergeReceiptResponse,
        stability="stable",
        owner_module=_MODULE,
        target_kinds=["item"],
        side_effects=["item_merge_receipt_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "merge_receipt.get",
        _writes.handle_get_merge_receipt,
        _writes.GetMergeReceiptRequest,
        _writes.GetMergeReceiptResponse,
        stability="stable",
        owner_module=_MODULE,
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
