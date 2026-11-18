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
    unattended: str = ""


def _visible(
    conn, viewer_session_id, previous_ids, include_resolved, *, presentation=False
):
    """Requests this seat sees, by the seat-coverage rule, with unattended notes."""
    from yoke_core.domain.steering_fleet_report_question_seats import (
        visible_questions,
    )

    if not viewer_session_id or not _table_exists(conn, "decision_requests"):
        return {}
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    open_status = (
        "status IN ('pending', 'resolved')" if include_resolved else "status='pending'"
    )
    watched = f" OR id IN ({','.join(p for _ in previous_ids)})" if previous_ids else ""
    columns = ("id", "status", "project_id", "audience_id", "requesting_session_id")
    rows = [
        {**dict(zip(columns, row[:5])), "subject_context": row[5]}
        for row in conn.execute(
            "SELECT id, status, "
            "project_id, audience_id, requesting_session_id, subject_context "
            "FROM decision_requests WHERE kind='operator_question' "
            f"AND ({open_status}{watched}) ORDER BY created_at, id",
            tuple(previous_ids),
        ).fetchall()
    ]
    if presentation:
        from yoke_core.domain.steering_fleet_report_question_seats import _context

        # Match read_questions' display rule before describing settled history.
        rows = [
            row
            for row in rows
            if row["status"] == "pending"
            or int(row["id"]) in previous_ids
            or _context(row["subject_context"]).get("answer_delivery", {}).get("reason")
        ]
        if not rows:
            return {}
    viewer = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id={p}",
        (viewer_session_id,),
    ).fetchone()
    notes = visible_questions(
        conn,
        viewer_session_id,
        rows,
        viewer_actor_id=viewer[0] if viewer else None,
    )
    return {
        int(row["id"]): (str(row["status"]), notes[int(row["id"])])
        for row in rows
        if int(row["id"]) in notes
    }


def question_states(
    conn, viewer_session_id, previous_ids=(), *, include_resolved=False
):
    """Open requests and watched departures this steering seat sees.

    Seat coverage decides, as for items and steering mail; the Inbox and
    ``decision-requests list`` still show every question.
    """
    return {
        request_id: state
        for request_id, (state, _) in _visible(
            conn, viewer_session_id, tuple(previous_ids), include_resolved
        ).items()
    }


def read_questions(conn, viewer_session_id, previous_ids=()):
    from yoke_core.domain.decision_request_rows import request_rows
    from yoke_core.domain.decision_request_operator_answer_delivery import answer_text
    from yoke_core.domain.actor_render import actor_labels_each
    from yoke_core.domain.item_ref_render import render_item_ref_lookup

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    seen = _visible(
        conn, viewer_session_id, tuple(previous_ids), True, presentation=True
    )
    ids = {request_id: state for request_id, (state, _) in seen.items()}
    rows = request_rows(conn, ids)
    shown = []
    for request_id in ids:
        row = rows[int(request_id)]
        reason = row["subject_context"].get("answer_delivery", {}).get("reason", "")
        if ids[request_id] != "pending" and not reason and request_id not in previous_ids:
            continue
        shown.append((request_id, row, reason))
    # Sessions, people and item refs are read once for every shown question;
    # per question they were three reads each.
    session_ids = tuple(dict.fromkeys(row["requesting_session_id"] for _, row, _ in shown))
    sessions = {
        str(found[0]): (found[1], found[2])
        for found in (
            conn.execute(
                "SELECT session_id, actor_id, executor FROM harness_sessions "
                f"WHERE session_id IN ({','.join(p for _ in session_ids)})",
                session_ids,
            ).fetchall()
            if session_ids
            else ()
        )
    }
    names = actor_labels_each(
        conn, [actor for actor, _ in sessions.values() if actor is not None]
    )
    refs = render_item_ref_lookup(
        conn,
        [row["subject_context"]["item_id"] for _, row, _ in shown
         if row["subject_context"].get("item_id")],
    )
    result = []
    for request_id, row, reason in shown:
        context = row["subject_context"]
        status = ids[request_id]
        session_id = row["requesting_session_id"]
        session = sessions.get(str(session_id))
        label = "ended session"
        if session:
            name = names.get(session[0], "person unavailable")
            label = f"{name} · {session[1]}"
        item = refs(context["item_id"]) if context.get("item_id") else "no item"
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
                f"answered ({answer_text(row)})"
                if status == "resolved"
                else f"superseded by request {row['superseded_by_request_id']}"
                if status == "superseded"
                else status,
                seen[request_id][1],
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
        note = f" · {row.unattended}" if row.unattended else ""
        lines.append(
            f"  request {row.request_id} · {row.session_label} · {row.item_ref}{note} · {age}m · {excerpt}{failure}"
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
