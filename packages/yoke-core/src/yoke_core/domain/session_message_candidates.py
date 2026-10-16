"""Thin session identities for recipient population and explicit anchors."""

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.session_message_liveness import applied_liveness
from yoke_core.domain.session_message_types import SessionMessageError


def candidate_identities(conn, selector):
    """Claims and role anchors resolve separately without a historical roster."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    clauses, params = [], []
    if selector.session_ids:
        clauses.append(
            f"session_id IN ({','.join(marker for _ in selector.session_ids)})"
        )
        params.extend(selector.session_ids)
    projects = []
    for raw in selector.projects:
        try:
            identity = resolve_project(conn, raw, required=True)
        except LookupError as exc:
            raise SessionMessageError(
                "target_not_found", str(exc), jsonpath="$.payload.selector.projects"
            ) from exc
        projects.append(identity.id)
    population = ""
    if selector.universe:
        population = "1=1"
    elif projects:
        population = f"project_id IN ({','.join(marker for _ in projects)})"
    if population:
        if "ended" not in applied_liveness(selector):
            population += " AND ended_at IS NULL AND terminated_at IS NULL"
        clauses.append(f"({population})")
        if not selector.universe:
            params.extend(projects)
    if not clauses:
        return {}
    rows = conn.execute(
        "SELECT session_id,project_id FROM harness_sessions WHERE "
        + " OR ".join(clauses)
        + " ORDER BY session_id",
        tuple(params),
    ).fetchall()
    return {str(row["session_id"]): dict(row) for row in rows}
