"""Validate a field note's explicit correlation with its root."""

from yoke_contracts.field_note_text import KIND_VALUES
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one


class FieldNoteCorrelationError(ValueError):
    """An invalid correlation with its recovery."""

    code = "field_note_correlation_invalid"


def validate_correlation(conn, *, project_id, correlation_id):
    """Return the root field-note id in this project, when supplied."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
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
            or str(row[3]) not in KIND_VALUES
        ):
            raise FieldNoteCorrelationError(
                "Correlation must name a field-note id in this project. Find the root with yoke feedback list, then pass --correlation-id ROOT_ID.",
            )
        root = int(row[2] or row[0])
    return root
