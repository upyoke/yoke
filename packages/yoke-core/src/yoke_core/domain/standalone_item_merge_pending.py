"""Result envelope for a queue admission that intentionally exits early."""

from __future__ import annotations

import json
from typing import Any


def clear_after_close_out(item_id: int, item: dict[str, Any]) -> str:
    """Clear a present marker; old control-plane item shapes are a no-op."""
    marker = item.get("merge_queue") or {}
    if not str(marker.get("enqueued_at") or ""):
        return ""
    from yoke_core.domain.merge_queue_landing_pending import clear_landing_pending

    return clear_landing_pending(item_id)


def envelope(
    *,
    item_id: int,
    public_ref: str,
    branch: str,
    target: str,
    status: str,
    outcome: Any,
) -> dict[str, Any]:
    """Return the stable enqueue-exit response without implying close-out."""
    return {
        "ok": True,
        "item_id": item_id,
        "public_ref": public_ref,
        "branch": branch,
        "target": target,
        "status": status,
        "landing_pending": True,
        "pr_number": outcome.pr_num,
        "commit_sha": outcome.commit_sha,
        "enqueued_at": outcome.enqueued_at,
        "evidence_recorded": False,
        "warnings": list(outcome.warnings),
    }


def print_envelope(
    item_id: int,
    public_ref: str,
    branch: str,
    target: str,
    status: str,
    outcome: Any,
) -> None:
    """Write the stable enqueue-exit response to stdout."""
    print(
        json.dumps(
            envelope(
                item_id=item_id,
                public_ref=public_ref,
                branch=branch,
                target=target,
                status=status,
                outcome=outcome,
            ),
            indent=2,
            sort_keys=True,
        )
    )


__all__ = ["clear_after_close_out", "envelope", "print_envelope"]
