"""Durable deduplication, correlation validation and session admission."""

from datetime import timedelta

from yoke_contracts.timestamps import utc_now
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import (
    instant_parameter,
    query_rows,
    query_one,
    query_scalar,
)

SESSION_NOTE_LIMIT = 10
SESSION_WARNING_AT = 8
BODY_PREFIX_LENGTH = 200
CORRELATION_RECIPE = "yoke ouroboros field-note append --kind observation --correlation-id ROOT_ID --evidence 'new evidence'"


class FieldNoteAdmissionError(ValueError):
    """A named admission refusal with its recovery."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def normalized_prefix(body):
    return " ".join(body.casefold().split())[:BODY_PREFIX_LENGTH]


def inspect_append(conn, *, project_id, author, body, session_id, correlation_id):
    """Hold admission locks through insert; return existing id, root and warning.

    Only distinct root notes consume the session budget. Corroborating evidence
    remains available after the cap so the refusal's recovery is usable.
    """
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    if db_backend.connection_is_postgres(conn):
        # Session lock spans authors/projects; project-author lock spans sessions.
        for key in (
            f"field-note-session:{session_id}",
            f"field-note-author:{project_id}:{author}",
        ):
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,)
            )
    root = None
    if correlation_id is not None:
        try:
            root = int(correlation_id)
        except (TypeError, ValueError):
            root = None
        row = (
            query_one(
                conn,
                f"SELECT id, project_id, correlation_id, category FROM ouroboros_entries WHERE id={p}",
                (root,),
            )
            if root is not None
            else None
        )
        if (
            row is None
            or row[1] != project_id
            or not str(row[3]).startswith("field-note-")
        ):
            raise FieldNoteAdmissionError(
                "field_note_correlation_invalid",
                "Correlation must name a field-note id in this project. Find the root with yoke ouroboros field-note list, then pass --correlation-id ROOT_ID.",
            )
        root = int(row[2] or row[0])
    scope = "project_id IS NULL" if project_id is None else f"project_id={p}"
    params = [] if project_id is None else [project_id]
    rows = query_rows(
        conn,
        "SELECT id, body, correlation_id FROM ouroboros_entries "
        f"WHERE {scope} AND agent={p} AND category LIKE {p} "
        f"AND created_at>={p} AND created_at<={p} ORDER BY id DESC",
        (
            *params,
            author,
            "field-note-%",
            instant_parameter(conn, utc_now() - timedelta(hours=24)),
            instant_parameter(conn, utc_now()),
        ),
    )
    prefix = normalized_prefix(body)
    for row in rows:
        if normalized_prefix(row[1]) == prefix:
            return str(row[0]), row[2], None
    count = (
        int(
            query_scalar(
                conn,
                f"SELECT COUNT(*) FROM ouroboros_entries WHERE session_id={p} AND category LIKE {p} AND correlation_id IS NULL",
                (session_id, "field-note-%"),
            )
            or 0
        )
        if session_id
        else 0
    )
    if root is None and count >= SESSION_NOTE_LIMIT:
        raise FieldNoteAdmissionError(
            "field_note_session_cap",
            f"This session has filed {count} distinct notes (limit {SESSION_NOTE_LIMIT}). Reuse an existing root for the same problem: {CORRELATION_RECIPE}. Keep unrelated findings in the current item's Progress Log for operator review; do not create another session to bypass the cap.",
        )
    warning = (
        f"This session has filed {count + 1}/{SESSION_NOTE_LIMIT} distinct notes. Link repeats with {CORRELATION_RECIPE}."
        if root is None and count + 1 >= SESSION_WARNING_AT
        else None
    )
    return None, root, warning
