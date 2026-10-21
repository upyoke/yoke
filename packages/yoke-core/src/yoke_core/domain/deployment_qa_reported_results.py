"""Which stage results and waits a run already reported to their audience.

A dispatch walks every member on every call, and a settled member stays
settled, so re-sending its result notice repeated the audience resolution
and message dedupe per member per call. A waiting member re-sent its
unchanged "still waiting" notice on every poll the same way. The sent notice
itself is the durable record: its idempotency key names the run, stage,
subject and target attempt (and, for a result, its outcome). One prefix read
per call answers every member; a cancelled notice no longer counts, so the
next poll sends it again.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.delivery_notice_kind import QA_RESULT_NOTICE_PREFIX
from yoke_core.domain.deployment_qa_result_notice import qa_result_idempotency_key
from yoke_core.domain.deployment_qa_stage_wake import (
    DEPLOYMENT_QA_STAGE_WAIT_PREFIX,
    run_stage_wait_idempotency_key,
    stage_wait_idempotency_key,
)


def _sent_keys(conn: Any, prefix: str) -> frozenset[str]:
    literal = "".join(f"\\{ch}" if ch in "\\%_" else ch for ch in prefix)
    rows = query_rows(
        conn,
        "SELECT idempotency_key FROM session_messages "
        "WHERE idempotency_key LIKE %s AND cancelled_at IS NULL",
        (literal + "%",),
    )
    return frozenset(str(row[0]) for row in rows)


def reported_stage_results(
    conn: Any, *, run_id: str, stage: Mapping[str, Any]
) -> Callable[[int | None, str, str], bool]:
    """Whether this stage already reported a (member, outcome, target) result."""
    notification = stage.get("notification")
    if not isinstance(notification, Mapping) or not notification.get("enabled"):
        return lambda _member, _outcome, _digest: False
    sent = _sent_keys(conn, f"{QA_RESULT_NOTICE_PREFIX}{run_id}:{stage['name']}:")
    return lambda member, outcome, digest: (
        qa_result_idempotency_key(run_id, str(stage["name"]), member, outcome, digest)
        in sent
    )


def sent_stage_waits(
    conn: Any, *, run_id: str, stage: Mapping[str, Any]
) -> Callable[[int | None, str], bool]:
    """Whether this stage already sent a (member, target) wait notice."""
    name = str(stage["name"])
    sent = _sent_keys(conn, f"{DEPLOYMENT_QA_STAGE_WAIT_PREFIX}{run_id}:{name}:")
    item_scoped = stage.get("scope") == "item"

    def woken(member: int | None, digest: str) -> bool:
        if item_scoped and member is not None:
            return stage_wait_idempotency_key(run_id, name, member, digest) in sent
        return run_stage_wait_idempotency_key(run_id, name, digest) in sent

    return woken


__all__ = ["reported_stage_results", "sent_stage_waits"]
