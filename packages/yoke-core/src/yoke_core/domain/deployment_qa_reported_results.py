"""Which settled stage results a run already reported to their audience.

A dispatch walks every member on every call, and a settled member stays
settled, so re-sending its result notice repeated the audience resolution
and message dedupe per member per call. The sent notice itself is the
durable record: its idempotency key names the run, stage, subject, outcome
and target attempt. One prefix read per call answers every member.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.delivery_notice_kind import QA_RESULT_NOTICE_PREFIX
from yoke_core.domain.deployment_qa_result_notice import qa_result_idempotency_key


def reported_stage_results(
    conn: Any, *, run_id: str, stage: Mapping[str, Any]
) -> Callable[[int | None, str, str], bool]:
    """Whether this stage already reported a (member, outcome, target) result."""
    notification = stage.get("notification")
    if not isinstance(notification, Mapping) or not notification.get("enabled"):
        return lambda _member, _outcome, _digest: False
    prefix = f"{QA_RESULT_NOTICE_PREFIX}{run_id}:{stage['name']}:"
    literal = "".join(f"\\{ch}" if ch in "\\%_" else ch for ch in prefix)
    rows = query_rows(
        conn,
        "SELECT idempotency_key FROM session_messages "
        "WHERE idempotency_key LIKE %s AND cancelled_at IS NULL",
        (literal + "%",),
    )
    sent = {str(row[0]) for row in rows}
    return lambda member, outcome, digest: (
        qa_result_idempotency_key(run_id, str(stage["name"]), member, outcome, digest)
        in sent
    )


__all__ = ["reported_stage_results"]
