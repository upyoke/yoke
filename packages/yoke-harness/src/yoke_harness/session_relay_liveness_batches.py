"""Deliver one poll's liveness records as requests the server will accept.

A relay reports everything the current poll observed, and a machine that has
been running for a while observes more than one request may carry. The
liveness request caps each of its collections, and an over-long collection
fails validation as a whole request: the server answers ``payload_invalid``
and nothing is delivered — not the first hundred records, not any of them.
A machine that has accumulated more records than the cap therefore reports
nothing at all, every poll, until someone notices; one relay repeated a
110-session request against a 100-record ceiling indefinitely.

Splitting at the cap the contract itself declares is what makes the report
deliverable again. Delivery stops at the first refusal rather than trying
the rest: whatever refused one request will usually refuse the next, and the
records behind an unsent batch are still on disk, so the next ordinary poll
reports them again. Nothing is dropped to fit — the caller spends only the
records the server acknowledged.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterator, Literal, Mapping, Sequence

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.session_control.function_ids import RELAY_LIVENESS_FUNCTION_ID
from yoke_contracts.session_control.relay_models import RELAY_REPORT_COLLECTION_LIMIT


_LOGGER = logging.getLogger(__name__)

LivenessCollection = Literal["sessions", "launches"]


def deliver_liveness_batches(
    dispatcher: Callable[..., Any],
    inventory: Any,
    *,
    collection: LivenessCollection,
    reports: Sequence[Mapping[str, Any]],
    timeout_s: int,
    refusal_label: str,
    limit: int = RELAY_REPORT_COLLECTION_LIMIT,
) -> Iterator[tuple[tuple[Mapping[str, Any], ...], Mapping[str, Any]]]:
    """Yield each batch the control plane accepted with what it answered.

    The caller spends a record — prunes it, releases it — only for a batch
    this yielded, so a refused or unsent batch leaves its records intact for
    the next poll. A refusal is logged with the caller's own label and ends
    the iteration; the poll it rides along with keeps working.
    """
    for start in range(0, len(reports), limit):
        batch = tuple(reports[start : start + limit])
        response = dispatcher(
            function_id=RELAY_LIVENESS_FUNCTION_ID,
            target=TargetRef(kind="global"),
            payload={
                "relay_id": inventory.relay_id,
                "machine_id": inventory.machine_id,
                "projects": list(inventory.project_ids),
                collection: list(batch),
            },
            timeout_s=timeout_s,
        )
        if not getattr(response, "success", False):
            error = getattr(response, "error", None)
            _LOGGER.warning(
                "%s refused (%s): %s; %d of %d records undelivered this poll",
                refusal_label,
                getattr(error, "code", "relay_liveness_failed"),
                getattr(error, "message", ""),
                len(reports) - start,
                len(reports),
            )
            return
        yield batch, getattr(response, "result", None) or {}


__all__ = ["deliver_liveness_batches", "LivenessCollection"]
