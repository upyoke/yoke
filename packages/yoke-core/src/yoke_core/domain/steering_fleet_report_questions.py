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


def read_questions(conn, project_ids):
    if not project_ids or not _table_exists(conn, "decision_requests"):
        return ()
    from yoke_core.domain.decision_request_rows import request_rows
    from yoke_core.domain.actor_render import actor_display_labels
    from yoke_core.domain.project_identity import render_item_ref

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM decision_requests WHERE kind='operator_question' "
            f"AND project_id IN ({','.join(p for _ in project_ids)}) "
            "AND status IN ('pending', 'resolved') ORDER BY created_at, id",
            tuple(project_ids),
        ).fetchall()
    ]
    rows = request_rows(conn, ids)
    result = []
    for request_id in ids:
        row = rows[int(request_id)]
        context = row["subject_context"]
        reason = context.get("answer_delivery", {}).get("reason", "")
        if row["status"] != "pending" and not reason:
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
