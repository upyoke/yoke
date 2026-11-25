"""Tell a launcher when a QA session ends without settling its work."""

from __future__ import annotations

import logging
from shlex import quote
from typing import Any, Mapping

from .db_helpers import query_one
from .db_savepoint import savepoint
from .qa_plan_execution_store import marker
from .session_qa_execution_holdings import session_owns_live_qa_execution
from .schema_common import _table_exists

_LOGGER = logging.getLogger(__name__)


def is_live_launcher(conn: Any, *, owner: str, caller: str) -> bool:
    """Whether this live session requested a launch that registered the owner."""
    if not _table_exists(conn, "session_launches"):
        return False
    p = marker(conn)
    return query_one(
        conn,
        "SELECT 1 FROM session_launches l JOIN harness_sessions s "
        "ON s.session_id=l.requester_session_id "
        f"WHERE l.registered_session_id={p} AND l.requester_session_id={p} "
        "AND s.ended_at IS NULL AND s.terminated_at IS NULL LIMIT 1",
        (owner, caller),
    ) is not None


def _partition_flags(conn: Any, launch: Any, execution: Mapping[str, Any] | None) -> str:
    from .project_identity import render_item_ref

    row = execution or {}
    item = row.get("item_id") or row.get("deployment_member_item_id")
    if row.get("deployment_run_id"):
        flags = f"--deployment-run-id {quote(row['deployment_run_id'])}"
        if row.get("deployment_stage"):
            flags += f" --stage {quote(row['deployment_stage'])}"
        if item is not None:
            flags += f" --item {quote(render_item_ref(conn, item))}"
        return flags
    item = launch.item_id if execution is None else item
    if item is not None:
        ref = render_item_ref(conn, item)
        flags = f"--item {quote(ref)}"
        if row.get("transition_id"):
            flags += f" --transition {quote(row['transition_id'])}"
        return flags
    from .function_target_row_project import slug_for_project_id

    flags = f"--project {quote(slug_for_project_id(conn, launch.project_id))}"
    if row.get("standalone_plan_id") is not None:
        flags += f" --plan {row['standalone_plan_id']}"
    return flags


def _notify(conn: Any, session_id: str) -> None:
    from yoke_contracts.session_control.models import RecipientSelector

    from .qa_plan_execution_reconcile import execution_project, subject_flag
    from .session_launch_abandonment import _launch_for_session
    from .session_message_service import send_message

    launch = _launch_for_session(conn, session_id)
    if launch is None or launch.registered_session_id != session_id or not launch.requester_session_id:
        return
    p = marker(conn)
    execution = None
    live = False
    if _table_exists(conn, "qa_plan_executions"):
        execution = query_one(
            conn,
            f"SELECT * FROM qa_plan_executions WHERE session_id={p} "
            "ORDER BY execution_order DESC LIMIT 1",
            (session_id,),
        )
        live = session_owns_live_qa_execution(conn, session_id)

    if not live:
        if not (launch.idempotency_key or "").startswith("qa-walk:"):
            return
        if query_one(
            conn,
            f"SELECT 1 FROM session_messages WHERE sender_session_id={p} "
            f"AND idempotency_key LIKE {p} LIMIT 1",
            (session_id, "qa-walk-result:%"),
        ):
            return

    flags = _partition_flags(conn, launch, execution)
    if execution is None:
        last = "It recorded no QA execution."
        recovery = "Relaunch the walker for the original subject."
    else:
        last = f"Its last QA execution was {execution['id']} ({execution['state']})."
        abort_flags = subject_flag(conn, execution, execution_project(conn, execution)[1])
        recovery = (
            f"Abort any execution it left live with launcher authority: "
            f"`yoke qa plan abort {abort_flags} --execution-id {execution['id']} --reason TEXT`. "
            "Then relaunch, or launch a replacement that adopts the execution."
        )
    send_message(
        conn,
        actor_id=launch.requester_actor_id,
        sender_session_id=None,
        selector=RecipientSelector(session_ids=[launch.requester_session_id]),
        body=(
            f"QA session from launch {launch.launch_id} ended in session {session_id}. {last} "
            f"Re-enter with `yoke qa plan partitions {flags}`. {recovery}"
        ),
        idempotency_key=f"qa-walk-ended:{launch.launch_id}",
        idempotency_intent_only=True,
        commit=False,
    )


def notify_ended_qa_walker(conn: Any, session_id: str) -> None:
    """Run after the session-end commit, independently of launch settlement."""
    if not _table_exists(conn, "session_launches"):
        return
    try:
        with savepoint(conn, "qa_walker_backstop", owns=True):
            _notify(conn, session_id)
        conn.commit()
    except Exception:
        _LOGGER.exception("Could not notify the launcher of ended QA session %s", session_id)
