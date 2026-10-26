"""A closed member's post-commit effects, never inside a held transaction.

A run's close-out spends most of its time outside the database, in GitHub
sync per member. A run retires no lanes: the status write already released
their rows and claims, and the lanes themselves live on worker machines,
where the standing relay's periodic sweep removes each clean, merged,
unclaimed one. No transaction may stay open across that work. The server ends a
session left idle in a transaction past its bound, and every later write on
that connection then fails with ``the connection is closed``.

So the effects never borrow the caller's connection. Each database step
opens its own connection, commits, and closes it before any file-system or
network work runs, and a connection that drops mid-step is reopened once:
every step is idempotent. A lost connection therefore costs at most the one
member whose step it carried, never the members after it.
"""

from __future__ import annotations

import io
from typing import Any, Callable

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.function_connection_loss import retry_dropped_connection
from yoke_core.domain.standalone_item_merge_evidence import CLOSED_OUT_STATUS


def _in_short_transaction(step: Callable[[Any], None]) -> None:
    """Run *step* on a fresh connection and commit; reopen once if it drops."""

    def _once() -> None:
        conn = connect()
        try:
            step(conn)
            conn.commit()
        finally:
            conn.close()

    retry_dropped_connection(_once)


def run_closed_member_effects(
    *,
    item_id: int,
    public_ref: str,
    receipt: Any = None,
) -> str:
    """Run a closed member's post-commit effects; name any that failed.

    Every step is idempotent, so a replay over a member whose effects
    already ran repeats nothing harmful. ``receipt`` is the status write's
    own effect receipt, held only by the pass that committed the close.
    Lanes are left to the relay's periodic sweep on the machine holding them.
    Returns ``""`` when every effect finished.
    """
    from yoke_core.domain.backlog_update_effects import (
        run_post_commit_update_effects,
    )
    from yoke_core.domain.standalone_item_merge import sync_item_to_github

    try:
        if receipt is not None:
            _in_short_transaction(
                lambda conn: run_post_commit_update_effects(
                    conn, receipt=receipt, out=io.StringIO()
                )
            )
        github_error = sync_item_to_github(int(item_id))
        _in_short_transaction(
            lambda conn: _end_previous_claim_holders_if_empty(conn, item_id=item_id)
        )
    except Exception as exc:  # noqa: BLE001 - reported; the close stays committed
        return str(exc) or exc.__class__.__name__
    if github_error:
        print(f"{public_ref}: GitHub sync skipped: {github_error}", flush=True)
    if receipt is not None:
        print(
            f"{public_ref}: post-deploy obligations satisfied; closed without a wake."
        )
    return ""


def _end_previous_claim_holders_if_empty(conn: Any, *, item_id: int) -> None:
    """End any previous holding sessions released by the transition if now empty."""
    from yoke_core.domain.sessions_render_end_if_empty import end_session_if_empty
    from yoke_core.domain.work_claim_targets import scope_int_sql

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    item_scope = scope_int_sql(conn, "scope", "item_id")
    epic_scope = scope_int_sql(conn, "scope", "epic_id")
    release_intent = f"item-terminal:{CLOSED_OUT_STATUS}"

    rows = conn.execute(
        "SELECT DISTINCT session_id FROM work_claims "
        f"WHERE release_reason_intent={marker} AND "
        f"((target_kind='item' AND {item_scope}={marker}) OR "
        f"(target_kind='epic_task' AND {epic_scope}={marker}))",
        (release_intent, int(item_id), int(item_id)),
    ).fetchall()

    session_ids = [
        str(row["session_id"] if hasattr(row, "keys") else row[0])
        for row in rows
        if row and (row["session_id"] if hasattr(row, "keys") else row[0])
    ]

    for session_id in sorted(set(session_ids)):
        try:
            end_session_if_empty(
                conn,
                session_id,
                triggered_by="delivery-satisfied-closeout",
            )
        except Exception:  # noqa: BLE001 - best-effort session cleanup
            pass


__all__ = ["run_closed_member_effects"]
