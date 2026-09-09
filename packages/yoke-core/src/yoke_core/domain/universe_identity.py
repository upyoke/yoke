"""The identity of the universe behind an open control-plane connection.

A universe is one organization identity card plus everything filed under
it (:func:`yoke_core.domain.org_schema.seed_default_org` refuses a second
one by name). That card is therefore the thing to point at when a
machine-local record has to say *which* control plane it is about, and it
needs no new column: the slug an operator chose plus the instant the row
was created distinguishes two universes that both took the neutral
default slug.

The fingerprint exists because an env label is a nickname. ``prod`` on
this machine can be re-pointed at a different server between two
commands, and every machine-local fact filed under that label — an actor
id above all — would silently start describing somebody else. Recording
the universe's own identity beside such a fact turns that retarget into a
refusal the operator can read.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists


def universe_fingerprint(conn: Any) -> Optional[str]:
    """Identity of the universe *conn* is open against, or ``None``.

    ``None`` means the question cannot be answered here — the database
    carries no organizations table yet, or it carries a number of them
    other than the exactly one a universe has. Callers treat that as "do
    not record or verify a binding", never as a match.
    """
    if not _table_exists(conn, "organizations"):
        return None
    try:
        rows = conn.execute(
            "SELECT slug, created_at FROM organizations ORDER BY id LIMIT 2"
        ).fetchall()
    except db_backend.operational_error_types(conn):
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 — the probe result is the product
            pass
        return None
    if len(rows) != 1:
        return None
    slug = str(rows[0][0] or "").strip()
    created_at = str(rows[0][1] or "").strip()
    if not slug or not created_at:
        return None
    return f"{slug}@{created_at}"


__all__ = ["universe_fingerprint"]
