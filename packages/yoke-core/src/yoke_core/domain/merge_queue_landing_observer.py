"""The control-plane reader that notices a landing without a waiting worker.

An item's landing used to be recorded only by the process waiting for it.
Both landing routes converge on the same pull request, but only the
two-call handoff recorded a queue admission, so a worker holding the
landing in its own turn left no durable trace at all — and when that turn
died, the merge was real on GitHub and invisible here: the item sat
non-terminal with no landing stamp, the fleet report showed an idle holder
rather than a landing nobody closed out, and a person had to notice by
hand.

So the pull request is recorded when it is opened
(:mod:`yoke_core.domain.merge_queue_landing_pending`), and this observer
reads GitHub for every non-terminal item that has one. Relay upkeep and a
waiting lane both call it, while the project cadence row makes those callers
share one GitHub sweep. A merge stamps the item's landing facts once and
notifies whoever owns the lane
(:mod:`yoke_core.domain.merge_queue_landing_notice`). Nothing here
transitions an item: close-out is evidence-bound work that belongs to a
claim holder, and a landing recorded without it is exactly the state the
report exists to surface.

What each candidate costs depends on which route it is on. An item whose
queue admission was recorded is waiting on a notification only this
observer sends, so it gets the full four-fact read and can be told its
landing stopped. An item that merely has a pull request open is asked one
question — did it merge — because the ordinary answer for a pull request
still being verified is *not yet*, and a landing that was never armed
cannot have been ejected from a queue it never entered.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.merge_queue_entry_checks import disarm_merge_when_ready
from yoke_core.domain.merge_queue_landing_candidates import (
    pending_landing_rows,
    read_candidate,
)
from yoke_core.domain.merge_queue_landing_record import (
    from_readback,
    write_landing_record,
)
from yoke_core.domain.merge_queue_landing_record_state import ENTRY_CHECKS_FAILED
from yoke_core.domain.merge_queue_landing_refresh import (
    REFRESH_CADENCE_SECONDS,
    claim_due_projects,
    complete_projects,
    fail_projects,
)
from yoke_core.domain.merge_queue_landing_notice import (
    landing_message,
    notice_already_sent,
    push_notice,
)
from yoke_core.domain.merge_queue_landing_observation import (
    EJECTED,
    LANDED,
    classify_pending_landing,
    ejection_message,
)
from yoke_core.domain.session_message_types import timestamp, utc_now
from yoke_core.engines.merge_worktree_pr_check_runs import read_required_checks
from yoke_core.engines.merge_worktree_pr_membership import read_pr_queue_membership
from yoke_core.engines.merge_worktree_pr_queue import read_pr_landing_state


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def observe_pending_landings(
    conn: Any,
    project_ids: Iterable[int],
    *,
    now: datetime | None = None,
    read_state: Callable[..., Any] = read_pr_landing_state,
    read_membership: Callable[..., Any] = read_pr_queue_membership,
    read_checks: Callable[..., Any] = read_required_checks,
    disarm: Callable[..., str] = disarm_merge_when_ready,
    cadence_seconds: float = REFRESH_CADENCE_SECONDS,
) -> dict[str, Any]:
    """Record every landing that happened, and report how each resolved.

    A landing that merged is stamped on the item and its holder is told to
    close out. A pull request the queue has dropped notifies the holder to
    rebase and re-gate, and its handoff marker is cleared, because there is
    no queued landing left to wait for. Anything GitHub is still holding
    stays silent. A notice failure is returned under ``notice_errors`` for
    that item without poisoning the rest of the project refresh.
    """
    current = now or utc_now()
    current_text = timestamp(current)
    projects = claim_due_projects(
        conn,
        project_ids,
        now=current,
        cadence_seconds=cadence_seconds,
    )
    result = {
        "checked": 0,
        "landed": 0,
        "notified": 0,
        "ejected": 0,
        "unrouted": 0,
    }
    if not projects:
        return result
    try:
        rows = pending_landing_rows(conn, projects)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        fail_projects(conn, projects, now=current, error=str(exc))
        raise
    result["checked"] = len(rows)
    marker = _p(conn)
    cycle_errors: list[str] = []
    for row in rows:
        item_id = int(row["id"])
        project_id = int(row["project_id"])
        pr_number = str(row["merge_queue_pr_number"])
        target = str(row.get("default_branch") or "main")
        try:
            ctx, readback = read_candidate(
                row,
                pr_number,
                target=target,
                read_state=read_state,
                read_membership=read_membership,
                read_checks=read_checks,
            )
            if readback.membership is not None or readback.merged:
                record = from_readback(
                    item_id=item_id,
                    project_id=project_id,
                    pr_number=pr_number,
                    readback=readback,
                    observed_at=current_text,
                )
                if record.state == ENTRY_CHECKS_FAILED:
                    record = record.with_disarm_note(disarm(ctx, pr_number))
                write_landing_record(conn, record)
                conn.commit()
        except Exception as exc:
            conn.rollback()
            cycle_errors.append(f"{render_item_ref(conn, item_id)}: {exc}")
            continue
        if readback.state_error:
            continue
        observation = classify_pending_landing(readback, target=target)
        if observation.kind not in (LANDED, EJECTED):
            continue
        public_ref = format_item_ref(
            row["slug"],
            row["public_item_prefix"],
            row["project_sequence"])
        notice_in_progress = False
        try:
            if observation.kind == EJECTED:
                # The notice's own identity carries the dedupe, not a column.
                # That is what lets an armed pull request the queue will never
                # admit be reported at all: it has no admission to clear, and
                # keying the report on one silenced it entirely.
                # Keyed on the head this observation read, not just the pull
                # request: the same PR number survives a force-push, so a
                # fresh commit that fails its own required checks is a new
                # ejection the holder has not heard about yet. Keying on the
                # PR alone collapsed that second, distinct stoppage onto the
                # first one's already-acknowledged message and the holder
                # never heard the queue had dropped it again.
                head_sha = readback.state.head_sha if readback.state else ""
                key = f"merge-queue-ejected:{item_id}:{pr_number}:{head_sha}"
                if notice_already_sent(conn, idempotency_key=key):
                    # Already reported for this exact head. The item stays a
                    # candidate — a queue that merges it after the rebase is
                    # a landing this observer must still see — but the stop
                    # is not news, and counting it again would report work
                    # that is not there.
                    conn.commit()
                    continue
                notice_in_progress = True
                delivery = push_notice(
                    conn,
                    item_id=item_id,
                    project_id=project_id,
                    body_for_route=lambda route: ejection_message(
                        public_ref, pr_number, observation, route
                    ),
                    idempotency_key=key,
                    now=current,
                )
                notice_in_progress = False
                if not delivery:
                    conn.commit()
                    result["unrouted"] += 1
                    continue
                # Acceptance ends the observer's responsibility. Delivery is
                # owned by the ordinary pending-message path. Only a recorded
                # admission is cleared: there is no queued landing left to
                # wait for, and a candidate that never reached the queue has
                # nothing to clear.
                if row.get("merge_queue_enqueued_at"):
                    conn.execute(
                        f"UPDATE items SET merge_queue_enqueued_at=NULL "
                        f"WHERE id={marker} AND merge_queue_pr_number={marker}",
                        (item_id, pr_number),
                    )
                result["ejected"] += 1
                conn.commit()
                continue
            state = readback.state
            # GitHub's own merge time, so a landing first read minutes later
            # ages from when it happened rather than from when it was
            # noticed — which is the number the close-out report shows.
            landed_at = (state.merged_at if state is not None else "") or current_text
            merge_commit = state.merge_commit_sha if state is not None else ""
            if not str(row.get("merge_queue_landed_at") or ""):
                # merged_at is assigned, not coalesced: the guard below fires
                # this once per landing, so the only value it could preserve
                # belongs to a landing this item has already replaced -- an
                # item repointed at a second pull request would otherwise go
                # on reporting the first one's merge time forever.
                cursor = conn.execute(
                    f"UPDATE items SET merge_queue_landed_at={marker}, "
                    f"merged_at={marker} "
                    f"WHERE id={marker} AND merge_queue_pr_number={marker} "
                    "AND merge_queue_landed_at IS NULL",
                    (landed_at, landed_at, item_id, pr_number),
                )
                if not cursor.rowcount:
                    conn.rollback()
                    continue
                result["landed"] += 1
            notice_in_progress = True
            delivery = push_notice(
                conn,
                item_id=item_id,
                project_id=project_id,
                body_for_route=lambda route: landing_message(
                    public_ref, pr_number, merge_commit, route
                ),
                idempotency_key=f"merge-queue-landed:{item_id}:{pr_number}",
                now=current,
            )
            notice_in_progress = False
            if not delivery:
                conn.commit()
                result["unrouted"] += 1
                continue
            if delivery == "delivered":
                conn.execute(
                    f"UPDATE items SET merge_queue_notified_at={marker} "
                    f"WHERE id={marker} AND merge_queue_pr_number={marker} "
                    "AND merge_queue_notified_at IS NULL",
                    (current_text, item_id, pr_number),
                )
                result["notified"] += 1
            conn.commit()
        except Exception as exc:
            conn.rollback()
            detail = f"{render_item_ref(conn, item_id)}: {exc}"
            if notice_in_progress:
                result.setdefault("notice_errors", []).append(
                    {"item_id": item_id, "pr_number": pr_number, "error": str(exc)}
                )
            else:
                cycle_errors.append(detail)
    if cycle_errors:
        fail_projects(conn, projects, now=current, error="; ".join(cycle_errors))
    else:
        complete_projects(conn, projects, now=current)
    return result


__all__ = ["observe_pending_landings"]
