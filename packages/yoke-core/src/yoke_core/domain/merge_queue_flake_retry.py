"""Reserve a failed train's single flake retry through its durable item owner."""

from __future__ import annotations

from yoke_core.domain.public_item_target import public_item_target

RETRY_SECTION = "Merge train retries"
RETRY_EXHAUSTED = "merge_train_flake_retry_exhausted"


def claim_retry(public_ref, pr_number, head, base, run_url, reason, *, dispatch=None):
    """Reserve before arming; uncertainty never authorizes another retry."""
    if dispatch is None:
        return (
            "merge_train_flake_retry_unrecorded: no control-plane dispatcher; "
            "use the governed yoke merge item command to reserve the retry; "
            "no re-enqueue was sent."
        )
    try:
        response = dispatch(
            function_id="merge_queue.flake_retry.claim",
            target=public_item_target(public_ref),
            payload={
                "pr_number": pr_number, "head_sha": head, "base_sha": base,
                "run_url": run_url, "reason": reason,
            },
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
    return None
