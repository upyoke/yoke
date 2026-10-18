"""Store every named QA success policy in its structured form.

Requirement writes accepted the bare policy name ``all-pass`` and stored it as
that text, and older rows hold ``all_pass``. Every reader decodes
``success_policy`` as JSON, so release admission refused an item carrying such
a row with a raw decode error. Writes now store a name as
``{"id":"all-pass","params":{}}``; this entry rewrites the rows already
stored either way into that same text, so storage holds one form. A build
that predates this entry already reads the structured form.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists

TABLE = "qa_requirements"
NAMED_FORMS = ("all-pass", "all_pass")
STRUCTURED_FORM = '{"id":"all-pass","params":{}}'


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def apply(conn: Any) -> None:
    """Rewrite each bare policy name to the structured form."""
    if not _table_exists(conn, TABLE):
        return
    marker = _p(conn)
    conn.execute(
        f"UPDATE {TABLE} SET success_policy = {marker} "
        f"WHERE success_policy IN ({marker}, {marker})",
        (STRUCTURED_FORM, *NAMED_FORMS),
    )


def invariants(conn: Any) -> None:
    """Prove no row stores a bare policy name."""
    if not _table_exists(conn, TABLE):
        return
    marker = _p(conn)
    remaining = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE success_policy IN ({marker}, {marker})",
        NAMED_FORMS,
    ).fetchone()[0]
    assert int(remaining) == 0, (
        f"{TABLE} still stores {remaining} bare success_policy name(s)"
    )


__all__ = ["NAMED_FORMS", "STRUCTURED_FORM", "TABLE", "apply", "invariants"]
