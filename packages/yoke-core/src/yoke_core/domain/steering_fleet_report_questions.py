"""Pending operator questions and failed answer delivery in steering reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


@dataclass(frozen=True)
class OperatorQuestion:
    request_id: int
    requesting_session_id: str
    session_label: str
    item_ref: str
    question: str
    created_at: Any
    delivery_reason: str = ""
    status: str = "pending"
    outcome: str = ""


def question_states(
    conn, project_ids, previous_ids=(), *, include_resolved=False, viewer_actor_id=None
):
    """Read open requests and watched departures inside the held projects."""
    if (not project_ids and viewer_actor_id is None) or not _table_exists(
        conn, "decision_requests"
    ):
        return {}
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    open_status = (
        "status IN ('pending', 'resolved') AND consumed_at IS NULL"
        if include_resolved
        else "status='pending' AND consumed_at IS NULL"
    )
    watched = f" OR id IN ({','.join(p for _ in previous_ids)})" if previous_ids else ""
    from yoke_core.domain.audiences import includes_actor

    project_clause = (
        f"project_id IN ({','.join(p for _ in project_ids)})" if project_ids else "1=0"
    )
    return {
        int(row[0]): str(row[1])
        for row in conn.execute(
            "SELECT id, CASE WHEN consumed_at IS NOT NULL THEN 'consumed' ELSE status END, project_id, audience_id FROM decision_requests WHERE kind='operator_question' "
            f"AND ({project_clause} OR project_id IS NULL) "
            f"AND ({open_status}{watched}) ORDER BY created_at, id",
            (*project_ids, *previous_ids),
        ).fetchall()
        if row[2] is not None
        or (
            viewer_actor_id is not None
            and includes_actor(conn, row[3], viewer_actor_id)
        )
    }


def read_questions(conn, project_ids, previous_ids=(), *, viewer_actor_id=None):
    from yoke_core.domain.decision_request_rows import request_rows
    from yoke_core.domain.decision_request_operator_answer_delivery import answer_text
    from yoke_core.domain.actor_render import actor_display_labels
    from yoke_core.domain.project_identity import render_item_ref

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    ids = question_states(
        conn,
        project_ids,
        previous_ids,
        include_resolved=True,
        viewer_actor_id=viewer_actor_id,
    )
    rows = request_rows(conn, ids)
    result = []
    for request_id in ids:
        row = rows[int(request_id)]
        context = row["subject_context"]
        status = ids[request_id]
        reason = context.get("answer_delivery", {}).get("reason", "")
        if status != "pending" and not reason and request_id not in previous_ids:
            continue
        session_id = row["requesting_session_id"]
        session = conn.execute(
            f"SELECT actor_id, executor FROM harness_sessions WHERE session_id={p}",
            (session_id,),
        ).fetchone()
        label = "ended session"
        if session:
            name = actor_display_labels(conn, [session[0]]).get(
                session[0], "person unavailable"
            )
            label = f"{name} · {session[1]}"
        item = (
            render_item_ref(conn, context["item_id"])
            if context.get("item_id")
            else "no item"
        )
        result.append(
            OperatorQuestion(
                int(request_id),
                session_id,
                label,
                item,
                context["question"],
                row["created_at"],
                reason,
                status,
                f"answered ({answer_text(row)})" if status == "resolved" else status,
            )
        )
    return tuple(result)


def question_lines(questions, now):
    if not questions:
        return []
    lines = ["## Questions waiting on you"]
    for row in questions:
        age = max(
            0,
            int(
                (parse_instant(now) - parse_instant(row.created_at)).total_seconds()
                // 60
            ),
        )
        excerpt = " ".join(row.question.split())[:160]
        failure = (
            f" · {row.delivery_reason}; read the answer and relay it"
            if row.delivery_reason
            else ""
        )
        lines.append(
            f"  request {row.request_id} · {row.session_label} · {row.item_ref} · {age}m · {excerpt}{failure}"
        )
    return [*lines, ""]


def previous_question_ids(fingerprint):
    """A pre-upgrade fingerprint has no request identities to recover."""
    import json

    try:
        value = json.loads(fingerprint) if fingerprint else {}
        ids = value.get("question_ids", []) if isinstance(value, dict) else []
        return tuple(int(value) for value in ids) if isinstance(ids, list) else ()
    except (ValueError, TypeError):
        return ()


def outcome_lines(questions):
    return [
        f"  request {row.request_id} no longer waiting: {row.outcome}"
        for row in questions
    ]
