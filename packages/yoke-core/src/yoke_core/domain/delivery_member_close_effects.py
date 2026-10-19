"""A closed member's post-commit effects, never inside a held transaction.

A run's close-out spends most of its time outside the database: GitHub
sync per member, then one sweep of each checkout's merged lanes after every
member has closed. A member's own lanes are not retired inline: the status
write already released their rows and claims, and the sweep removes each
clean, merged, unclaimed lane, so a member's close-out never waits on git.
No transaction may stay open across that work. The server ends a
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
import sys
from typing import Any, Callable

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
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


def _closed_item(public_ref: str) -> tuple[dict[str, Any], str]:
    """The closed member as the lane sweep reads it, or why it could not.

    The same ``items.detail.get`` read a standalone close-out retires lanes
    from: the project names this machine's checkout and the target branch.
    """
    try:
        response = call_dispatcher(
            function_id="items.detail.get",
            target=TargetRef(kind="item", public_ref=public_ref),
            payload={},
        )
    except Exception as exc:  # noqa: BLE001 - reported as a cleanup warning
        return {}, str(exc) or exc.__class__.__name__
    if not response.success:
        error = response.error
        return {}, error.message if error is not None else "item read refused"
    return (response.result or {}).get("item") or {}, ""


def sweep_closed_member_checkouts(public_refs: list[str]) -> list[str]:
    """Sweep each distinct checkout of these closed members once.

    The run calls this after every member has closed; it is the only place
    a run retires its members' lanes. A member whose checkout this machine
    cannot sweep is named with the recovery that retires its lanes.
    """
    from yoke_core.domain.terminal_lane_cleanup import (
        item_lane_checkout,
        sweep_managed_lanes,
    )
    from yoke_core.domain.worktree_capacity import DOCTOR_RETIRE_RECIPE

    def _emit(message: str, **_kw: Any) -> None:
        print(message, file=sys.stderr, flush=True)

    seen: set[tuple[str, str]] = set()
    warnings: list[str] = []
    for public_ref in public_refs:
        item, refusal = _closed_item(public_ref)
        resolved = None if refusal or not item else item_lane_checkout(item)
        if resolved is None:
            reason = (
                f"the item could not be read ({refusal or 'no item returned'})"
                if refusal or not item
                else "checkout unavailable on this machine"
            )
            warnings.append(
                f"{public_ref}: lane sweep skipped: {reason}; retire its lanes "
                f"with `{DOCTOR_RETIRE_RECIPE}` on the machine holding them"
            )
            continue
        root, target = resolved
        key = (str(root), target)
        if key in seen:
            continue
        seen.add(key)
        found, _payload = sweep_managed_lanes(repo_root=root, target=target, emit=_emit)
        warnings.extend(found)
    return warnings


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
    Lanes are left to :func:`sweep_closed_member_checkouts`.
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


__all__ = ["run_closed_member_effects", "sweep_closed_member_checkouts"]
