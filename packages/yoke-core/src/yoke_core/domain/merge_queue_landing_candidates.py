"""Which items have a landing to read, and how much of it to ask GitHub.

Split from the observer because these are reading decisions, not
resolution ones: the candidate set is a bounded query over live work, and
how much each candidate costs follows from whether GitHub is holding its
landing at all.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from yoke_core.domain import db_backend
from yoke_core.domain.conflict_survey_declared_paths import TERMINAL_STATUSES
from yoke_core.domain.merge_queue_enqueue_verification import (
    LandingReadback,
    admission_facts_for_state,
    read_landing,
)
from yoke_core.domain.schema_common import _column_exists
from yoke_core.domain.merge_queue_readback_outcomes import (
    ENQUEUED,
    MERGE_WHEN_READY_ARMED,
)
from yoke_core.domain.session_message_types import row_dict
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def pending_landing_rows(conn: Any, project_ids: Iterable[int]) -> list[dict[str, Any]]:
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
        "i.merge_queue_enqueued_at, i.merge_queue_landed_at, "
        "CASE WHEN l.pr_number=i.merge_queue_pr_number AND "
        f"(l.merge_when_ready={marker} OR l.queue_holding={marker}) "
        "THEN 1 ELSE 0 END AS previously_held, p.slug, "
        "p.public_item_prefix, p.default_branch "
        "FROM items i JOIN projects p ON p.id=i.project_id "
        "LEFT JOIN merge_queue_landing_records l ON l.item_id=i.id "
        f"WHERE i.project_id IN ({slots}) "
        "AND i.merge_queue_pr_number IS NOT NULL "
        "AND i.merge_queue_notified_at IS NULL "
        f"AND i.status NOT IN ({terminal_slots}) ORDER BY i.id",
        (MERGE_WHEN_READY_ARMED, ENQUEUED, *projects, *terminal),
    ).fetchall()
    return [row_dict(row) for row in rows]


def read_candidate(
    row: dict[str, Any],
    pr_number: str,
    *,
    target: str,
    read_state: Callable[..., Any],
    read_membership: Callable[..., Any],
    read_checks: Callable[..., Any],
) -> tuple[MergeContext, LandingReadback]:
    """Ask GitHub only what this candidate's landing route can answer.

    Current or previously observed armedness decides the cost. An item with a
    recorded queue admission is owed the full four-fact read: it can be
    ejected, and only this observer would notice. So is an armed pull
    request that has not reached the queue — GitHub creates the entry only
    once the pull request's own required checks pass, so one whose checks
    concluded red can never be admitted, and asking it only "did it merge"
    answered "not yet" forever while its holder sat parked on a landing
    that was already over.

    The existing durable observation also proves a landing was held when
    no admission timestamp was recorded. GitHub clearing merge-when-ready
    must not turn that landing into a never-armed pull request: complete the
    four-fact read so the observer can send its stopped notice. Match that
    evidence to this pull request, never its predecessor.

    A pull request nobody armed costs one question. It cannot have been
    ejected from a queue it never entered, and a readback carrying no queue
    standing classifies as still waiting, so it is never mistaken for one
    the queue has dropped.
    """
    ctx = MergeContext(
        args=MergeArgs(branch="", target=target),
        repo_root="",
        project=str(row["slug"]),
    )
    if row.get("merge_queue_enqueued_at") or row.get("previously_held"):
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
    if state is not None and not state.merged and not state.auto_merge_active:
        return ctx, LandingReadback(state=state, state_error=state_error or "")
    return ctx, admission_facts_for_state(
        ctx,
        pr_number,
        state,
        state_error or "",
        read_membership=read_membership,
        read_checks=read_checks,
    )


__all__ = ["pending_landing_rows", "read_candidate"]
