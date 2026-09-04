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
from yoke_core.domain.conflict_survey_declared_paths import TERMINAL_STATUSES
from yoke_core.domain.merge_queue_enqueue_verification import (
    LandingReadback,
    read_landing,
)
from yoke_core.domain.merge_queue_entry_checks import disarm_merge_when_ready
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
from yoke_core.domain.merge_queue_landing_notice import landing_message, push_notice
from yoke_core.domain.merge_queue_landing_observation import (
    EJECTED,
    LANDED,
    classify_pending_landing,
    ejection_message,
)
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.session_message_types import row_dict, timestamp, utc_now
from yoke_core.engines.merge_worktree_pr_check_runs import read_required_checks
from yoke_core.engines.merge_worktree_pr_membership import read_pr_queue_membership
from yoke_core.engines.merge_worktree_pr_queue import read_pr_landing_state
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _pending_rows(conn: Any, project_ids: Iterable[int]) -> list[dict[str, Any]]:
    """Every non-terminal item that has a landing pull request to read.

    The pull request is the candidate key rather than the queue admission,
    because the admission exists on only one of the two landing routes. The
    set stays bounded by live work: a notified landing drops out at once,
    and close-out clears the pull request number outright.
    """
    projects = tuple(sorted({int(value) for value in project_ids}))
    if not projects or not _column_exists(conn, "items", "merge_queue_enqueued_at"):
        return []
    marker = _p(conn)
    slots = ",".join(marker for _ in projects)
    terminal = sorted(TERMINAL_STATUSES)
    terminal_slots = ",".join(marker for _ in terminal)
    rows = conn.execute(
        "SELECT i.id, i.project_id, i.project_sequence, i.merge_queue_pr_number, "
        "i.merge_queue_enqueued_at, i.merge_queue_landed_at, p.slug, "
        "p.public_item_prefix, p.default_branch "
        "FROM items i JOIN projects p ON p.id=i.project_id "
        f"WHERE i.project_id IN ({slots}) "
        "AND i.merge_queue_pr_number IS NOT NULL "
        "AND i.merge_queue_notified_at IS NULL "
        f"AND i.status NOT IN ({terminal_slots}) ORDER BY i.id",
        (*projects, *terminal),
    ).fetchall()
    return [row_dict(row) for row in rows]


def _read_candidate(
    row: dict[str, Any],
    pr_number: str,
    *,
    target: str,
    read_state: Callable[..., Any],
    read_membership: Callable[..., Any],
    read_checks: Callable[..., Any],
) -> tuple[MergeContext, LandingReadback]:
    """Ask GitHub only what this candidate's landing route can answer.

    An item with a recorded queue admission is owed the full four-fact
    read: it can be ejected, and only this observer would notice. An item
    that merely has a pull request open is asked whether it merged, and a
    readback carrying no queue standing classifies as still waiting — so a
    pull request that was never armed is never mistaken for one the queue
    has dropped.
    """
    ctx = MergeContext(
        args=MergeArgs(branch="", target=target),
        repo_root="",
        project=str(row["slug"]),
    )
    if row.get("merge_queue_enqueued_at"):
        return (
            ctx,
            read_landing(
                ctx,
                pr_number,
                read_state=read_state,
                read_membership=read_membership,
                read_checks=read_checks,
            ),
        )
    state, state_error = read_state(ctx, pr_number)
    return ctx, LandingReadback(state=state, state_error=state_error or "")


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
) -> dict[str, int]:
    """Record every landing that happened, and report how each resolved.

    A landing that merged is stamped on the item and its holder is told to
    close out. A pull request the queue has dropped notifies the holder to
    rebase and re-gate, and its handoff marker is cleared, because there is
    no queued landing left to wait for. Anything GitHub is still holding
    stays silent.
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
        rows = _pending_rows(conn, projects)
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
            ctx, readback = _read_candidate(
                row,
                pr_number,
                target=target,
                read_state=read_state,
                read_membership=read_membership,
                read_checks=read_checks,
            )
            if row.get("merge_queue_enqueued_at") or readback.merged:
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
            cycle_errors.append(f"item {item_id}: {exc}")
            continue
        if readback.state_error:
            continue
        observation = classify_pending_landing(readback, target=target)
        if observation.kind not in (LANDED, EJECTED):
            continue
        public_ref = format_item_ref(
            row["slug"],
            row["public_item_prefix"],
            row["project_sequence"],
            item_id=item_id,
        )
        try:
            if observation.kind == EJECTED:
                # An ejection whose admission is already cleared has been
                # reported once. The item stays a candidate — its pull
                # request is still open, and a queue that merges it after
                # the rebase is a landing this observer must still see — but
                # saying so again is noise, and the notice was idempotent
                # anyway.
                if not row.get("merge_queue_enqueued_at"):
                    continue
                delivery = push_notice(
                    conn,
                    item_id=item_id,
                    project_id=project_id,
                    body_for_route=lambda route: ejection_message(
                        public_ref, pr_number, observation, route
                    ),
                    idempotency_key=f"merge-queue-ejected:{item_id}:{pr_number}",
                    now=current,
                )
                if not delivery:
                    conn.commit()
                    result["unrouted"] += 1
                    continue
                if delivery == "delivered":
                    # The queue admission is what ended, so that is what is
                    # cleared: the item stops being reported as an armed
                    # landing and a fresh `yoke merge item` re-arms it. The
                    # pull request number stays, because one observation
                    # cannot separate an ejection from the seconds in which
                    # a successful train has cleared the slot and the merge
                    # has not surfaced — and a re-entry that turns out to be
                    # converging on a merge still needs that number to find
                    # the merge-group run its evidence is built on.
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
                cursor = conn.execute(
                    f"UPDATE items SET merge_queue_landed_at={marker}, "
                    f"merged_at=COALESCE(merged_at, {marker}) "
                    f"WHERE id={marker} AND merge_queue_pr_number={marker} "
                    "AND merge_queue_landed_at IS NULL",
                    (landed_at, landed_at, item_id, pr_number),
                )
                if not cursor.rowcount:
                    conn.rollback()
                    continue
                result["landed"] += 1
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
            cycle_errors.append(f"item {item_id}: {exc}")
    if cycle_errors:
        fail_projects(conn, projects, now=current, error="; ".join(cycle_errors))
    else:
        complete_projects(conn, projects, now=current)
    return result


__all__ = ["observe_pending_landings"]
