"""Requester identity, held item checks, and question history."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.decision_request_operator_question import invalid, slug


def validate_requester(conn, session_id, project_id, subject_key, context):
    from yoke_core.domain.decision_requests import _p
    from yoke_core.domain.work_claim_targets import scope_int_sql

    if not session_id or not subject_key.startswith(session_id + ":"):
        raise invalid("requesting_session_id is required and must prefix subject_key")
    if not slug(subject_key[len(session_id) + 1 :]):
        raise invalid("question key must be a lowercase slug")
    p = _p(conn)
    row = conn.execute(
        f"SELECT project_id, ended_at, terminated_at FROM harness_sessions WHERE session_id={p}",
        (session_id,),
    ).fetchone()
    if row is None or row[1] is not None or row[2] is not None:
        raise invalid("requesting session must exist and be live")
    if row[0] != project_id:
        raise invalid("requesting session must belong to the question project")
    item_id = context.get("item_id")
    if item_id is not None:
        item_scope = scope_int_sql(conn, "scope", "item_id")
        held = conn.execute(
            f"SELECT 1 FROM work_claims WHERE session_id={p} AND target_kind='item' "
            f"AND released_at IS NULL AND {item_scope}={p}",
            (session_id, item_id),
        ).fetchone()
        if held is None:
            raise invalid("item_id must name the requesting session's held item")


def list_questions(conn: Any, session_id: str, status: str | None = None):
    from yoke_core.domain.decision_requests import _p
    from yoke_core.domain.decision_request_rows import request_rows

    p = _p(conn)
    params = [session_id]
    clause = ""
    if status is not None:
        if status not in {"pending", "resolved", "withdrawn"}:
            raise invalid("status must be pending, resolved or withdrawn")
        clause = f" AND status={p}"
        params.append(status)
    ids = [
        row[0]
        for row in conn.execute(
            f"SELECT id FROM decision_requests WHERE requesting_session_id={p} "
            f"AND kind='operator_question'{clause} ORDER BY created_at, id",
            tuple(params),
        ).fetchall()
    ]
    rows = request_rows(conn, ids)
    from yoke_core.domain.decision_request_operator_answer_delivery import answer_text
    from yoke_core.domain.actor_render import actor_display_labels

    for row in rows.values():
        row["question_excerpt"] = row["subject_context"]["question"][:160]
        row["answer"] = answer_text(row) if row["status"] == "resolved" else None
        actor_id = row.get("resolution_actor_id")
        row["answered_by"] = (
            actor_display_labels(conn, [actor_id]).get(actor_id) if actor_id else None
        )
        row["answered_at"] = row.get("resolved_at")
    return [rows[int(request_id)] for request_id in ids]


def describe_question(conn, row):
    from yoke_core.domain.decision_requests import _p
    from yoke_core.domain.actor_render import actor_display_labels
    from yoke_core.domain.project_identity import render_item_ref

    session = conn.execute(
        f"SELECT actor_id, executor FROM harness_sessions WHERE session_id={_p(conn)}",
        (row["requesting_session_id"],),
    ).fetchone()
    if session is not None:
        name = actor_display_labels(conn, [session[0]]).get(
            session[0], "person unavailable"
        )
        row["requesting_session_label"] = f"{name} · {session[1]}"
    if row["subject_context"].get("item_id"):
        row["subject_context"]["item_ref"] = render_item_ref(
            conn, row["subject_context"]["item_id"]
        )


def cancellation_authority(conn, request, session_id, actor_id):
    from yoke_core.domain.decision_requests import _p
    from yoke_core.domain.session_steering_authority import covering_session_seat

    if request["kind"] != "operator_question" or request["status"] != "pending":
        raise invalid("only a pending operator_question can be cancelled")
    caller = conn.execute(
        f"SELECT actor_id FROM harness_sessions WHERE session_id={_p(conn)} "
        "AND ended_at IS NULL AND terminated_at IS NULL",
        (session_id,),
    ).fetchone()
    if caller is None or caller[0] != actor_id:
        raise PermissionError(
            "operator_question_cancel_forbidden: use the requesting session or a live steering seat"
        )
    if session_id == request["requesting_session_id"]:
        return "requesting session cancelled the question"
    if covering_session_seat(
        conn,
        caller_session_id=session_id,
        target={
            "project_id": request["project_id"],
            "item_id": request["subject_context"].get("item_id"),
        },
    ):
        return "steering cancelled the question"
    raise PermissionError(
        "operator_question_cancel_forbidden: ask the requesting session or steering to withdraw it"
    )


def file_question(conn, *, replaces=None, **kwargs):
    """Replace and file in one transaction; the shared withdrawal owns the write."""
    from yoke_core.domain.db_savepoint import savepoint
    from yoke_core.domain.decision_requests import create_decision_request, _p
    from yoke_core.domain.decision_request_rows import request_row
    from yoke_core.domain.decision_request_resolution import withdraw_for_ended_subject

    with savepoint(conn, "file_operator_question", owns=False):
        if replaces is not None:
            suffix = " FOR UPDATE" if _p(conn) == "%s" else ""
            old = conn.execute(
                f"SELECT id FROM decision_requests WHERE id={_p(conn)}{suffix}",
                (replaces,),
            ).fetchone()
            if old is None:
                raise invalid(
                    "operator_question_replace_invalid: replaced request does not exist"
                )
            prior = request_row(conn, replaces)
            if (
                prior["kind"] != "operator_question"
                or prior["status"] != "pending"
                or prior["requesting_session_id"] != kwargs["requesting_session_id"]
            ):
                raise invalid(
                    "operator_question_replace_invalid: replace a pending question from the same requesting session"
                )
            withdraw_for_ended_subject(
                conn,
                replaces,
                reason="replacement being filed",
                actor_id=kwargs["originator_actor_id"],
                session_id=kwargs["session_id"],
                question_cancellation=True,
                commit=False,
            )
        row, created = create_decision_request(conn, **kwargs, commit=False)
        if replaces is not None:
            conn.execute(
                f"UPDATE decision_requests SET withdrawal_reason={_p(conn)} WHERE id={_p(conn)}",
                (f"Replaced by decision request {row['id']}", replaces),
            )
    conn.commit()
    return row, created
