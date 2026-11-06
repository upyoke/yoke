"""Reconcile correction landings before deciding release admission."""

from yoke_contracts.timestamps import utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.merge_queue_landing_attempt import (
    close_attempt,
    closed_unmerged_reason,
    read_open_attempts,
)
from yoke_core.domain.merge_queue_landing_identity import stamp_landing
from yoke_core.domain.merge_queue_landing_marker import promote_landing_attempt
from yoke_core.domain.item_ref_render import render_item_ref_lookup
from yoke_core.domain.merge_context import MergeArgs, MergeContext
from yoke_core.domain.merge_github_queue import read_pr_landing_state


def open_landing_refusals(conn, item_ids):
    attempts = read_open_attempts(conn, item_ids)
    if not attempts:
        return {}
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    slots = ",".join(marker for _ in attempts)
    rows = conn.execute(
        "SELECT i.id,p.slug,p.default_branch FROM items i "
        "JOIN projects p ON p.id=i.project_id "
        f"WHERE i.id IN ({slots})",
        tuple(attempts),
    ).fetchall()
    ref = render_item_ref_lookup(conn, attempts)
    errors = {}
    with savepoint(conn, "release_landing_refresh", owns=False):
        for row in rows:
            item_id, project, target = row[0], row[1], row[2]
            attempt = attempts[int(item_id)]
            pr = attempt["pr_number"]
            ctx = MergeContext(
                args=MergeArgs(branch="", target=target or "main"),
                repo_root="",
                project=project,
            )
            state, error = read_pr_landing_state(ctx, pr)
            if error or state is None:
                errors[int(item_id)] = (
                    f" Landing read unavailable: {error or 'no GitHub state'}; "
                    "repair GitHub read access and retry."
                )
                continue
            if state.merged:
                if promote_landing_attempt(conn, int(item_id), pr):
                    stamp_landing(
                        conn,
                        item_id=int(item_id),
                        pr_number=pr,
                        state=state,
                        landed_at=state.merged_at or utc_now(),
                    )
            elif state.closed:
                close_attempt(conn, int(item_id), pr, closed_unmerged_reason(pr))
    # Re-read so a concurrent settlement or replacement owns its actual record.
    return {
        item_id: (
            f"item_landing_open: {ref(item_id)} has open correction pull request "
            f"#{attempt['pr_number']}; wait for that landing to merge or close, "
            "then refresh the candidate and retry release enrollment and containment."
            + errors.get(item_id, "")
        )
        for item_id, attempt in read_open_attempts(conn, attempts).items()
    }


def require_closed_landings(conn, item_ids):
    refusals = open_landing_refusals(conn, item_ids)
    if refusals:
        raise ValueError(refusals[min(refusals)])


def require_closed_landing(conn, item_id):
    require_closed_landings(conn, (int(item_id),))
