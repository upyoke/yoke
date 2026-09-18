"""The merge-group receipt a landing already recorded, read back.

Close-out runs more than once for a member that parks at a release wait:
once when its train lands, and again at the deployment wake hours later.
Only the first of those runs while GitHub's ``merge_group`` runs collection
still reaches the train. The second one is the same bookkeeping against the
same durable landing, so it reads what the first one wrote rather than
asking GitHub the question a second time.

That ordering is what makes the ladder honest. The recorded receipt is
evidence this item's own landing produced; re-deriving it can only ever
agree with it or fail, and failing is what stranded members whose proof was
sitting in their own QA rows the whole time.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from yoke_contracts.api.function_call import TargetRef

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.merge_queue_batch_receipt import BatchReceipt


def recorded_receipt(
    item_id: int,
    *,
    pr_num: str,
    dispatch: Callable[..., Any] = call_dispatcher,
) -> Optional[BatchReceipt]:
    """The receipt this item recorded for ``pr_num``, or ``None``.

    ``None`` covers both "never recorded" and "could not be read": either
    way the caller's next rung is the derivation, which is exactly what it
    would have done without this read. A failure here therefore narrows no
    outcome that was previously reachable.
    """
    response = dispatch(
        function_id="merge.tests.recorded_queue_receipt",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={"pr_num": str(pr_num or "")},
    )
    if not getattr(response, "success", False):
        return None
    result = getattr(response, "result", None) or {}
    if not result.get("found"):
        return None
    head_sha = str(result.get("combined_head_sha") or "").strip()
    run_url = str(result.get("run_url") or "").strip()
    if not head_sha or not run_url:
        return None
    drift = result.get("drift_check")
    return BatchReceipt(
        pr_num=str(result.get("pr_num") or pr_num),
        merge_sha=str(result.get("merge_sha") or ""),
        members=tuple(str(member) for member in (result.get("members") or [])),
        head_sha=head_sha,
        run_url=run_url,
        drift_check=dict(drift) if isinstance(drift, dict) else {},
    )


__all__ = ["recorded_receipt"]
