"""Feedback reporter facts from the authenticated universe."""

from yoke_core.domain.project_identity import placeholder


def actor_email(conn, actor_id):
    if not str(actor_id or "").isdigit():
        return None
    row = conn.execute(
        "SELECT email FROM actor_external_identities "
        f"WHERE actor_id={placeholder(conn)} AND email IS NOT NULL "
        "AND email<>'' ORDER BY id LIMIT 1", (actor_id,)).fetchone()
    return row[0] if row else None

