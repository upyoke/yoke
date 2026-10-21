"""Reserve a failed train's single flake retry through its durable item owner."""

from __future__ import annotations

from uuid import uuid4

from yoke_core.domain.public_item_target import public_item_target

RETRY_SECTION = "Merge train retries"
RETRY_EXHAUSTED = "merge_train_flake_retry_exhausted"


def claim_retry(public_ref, pr_number, head, base, run_url, reason, *, dispatch=None, reservation=None):
    """Reserve before arming; uncertainty never authorizes another retry."""
    if dispatch is None:
        return (
            "merge_train_flake_retry_unrecorded: no control-plane dispatcher; "
            "use the governed yoke merge item command to reserve the retry; "
            "no re-enqueue was sent."
        )
    payload = {
        "pr_number": pr_number, "head_sha": head, "base_sha": base,
        "run_url": run_url, "reason": reason, "reservation_id": str(uuid4()),
    }
    try:
        response = dispatch(
            function_id="merge_queue.flake_retry.claim",
            target=public_item_target(public_ref),
            payload=payload,
        )
    except Exception as exc:  # noqa: BLE001 - unknown write must not arm
        return (
            f"merge_train_flake_retry_unrecorded: {exc}; inspect the item's "
            f"{RETRY_SECTION} section and restore the control-plane write before retrying."
        )
    if not response.success:
        error = response.error
        return (
            f"{getattr(error, 'code', 'merge_train_flake_retry_unrecorded')}: "
            f"{getattr(error, 'message', 'retry claim failed')}; no re-enqueue was sent."
        )
    if (response.result or {}).get("claimed") is not True:
        return (
            "merge_train_flake_retry_unrecorded: no reservation receipt; "
            "restore a matching serving build before retrying; no re-enqueue was sent."
        )
    if reservation is not None:
        reservation.update(payload)
    return None


def release_retry(public_ref, reservation, *, dispatch, rejected=True):
    """Restore only this attempt's budget after GitHub rejected entry."""
    if not rejected:
        return (
            "merge_train_flake_retry_entry_uncertain: the queue mutation reply "
            "does not prove rejection; its retry reservation remains spent. "
            "Inspect GitHub's identified PR/train before recovery; do not re-arm."
        )
    try:
        response = dispatch(
            function_id="merge_queue.flake_retry.claim",
            target=public_item_target(public_ref),
            payload={**reservation, "action": "release"},
        )
        if response.success and (response.result or {}).get("released") is True:
            return ""
        detail = getattr(response.error, "message", "missing release receipt")
    except Exception as exc:  # noqa: BLE001 - unknown release stays reserved
        detail = str(exc)
    return (
        f"merge_train_flake_retry_release_unrecorded: {detail}; queue entry failed "
        "but its reservation remains held. Ask the control-plane operator to "
        "restore reservation writes and reconcile this failed entry's "
        f"reservation {reservation['reservation_id']} before retrying."
    )
