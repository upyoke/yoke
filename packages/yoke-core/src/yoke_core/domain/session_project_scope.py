"""Canonical session-project scope resolver.

`/yoke do` no longer infers scope from the workspace path: the default is
"every registered project," and `--project yoke,buzz` narrows. The
workspace string still rides in the offer envelope for observability, but it
does not influence which projects are in scope.
"""

from __future__ import annotations

from typing import Any, List, Optional, Union

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project, row_value


def resolve_session_project_scope(
    conn: Any,
    *,
    override: Optional[List[Union[str, int]]] = None,
) -> List[int]:
    """Return the project ids in scope for this session.

    - `override` non-empty → resolve each slug or numeric id against
      ``projects`` and return canonical numeric ids.
    - Otherwise → return every registered project id (all-projects default).

    Unknown overrides raise ``ValueError`` naming the unknown value and the
    registered set. An empty list or ``None`` override is treated as no
    override (returns the all-projects default).
    """
    registered = _list_registered_project_ids(conn)
    if not override:
        return registered

    resolved: List[int] = []
    for project in override:
        try:
            ident = resolve_project(conn, project, required=True)
        except LookupError as exc:
            known = ", ".join(_list_registered_project_refs(conn))
            raise ValueError(
                f"Unknown project {project!r} in --project override. "
                f"Registered projects: {known or '(none)'}."
            ) from exc
        except db_backend.operational_error_types(conn) as exc:
            if db_backend.connection_is_postgres(conn):
                try:
                    conn.rollback()
                except Exception:
                    pass
            fallback_id = _fallback_project_id(project)
            if fallback_id is None:
                known = ", ".join(str(pid) for pid in registered)
                raise ValueError(
                    f"Unknown project {project!r} in --project override. "
                    f"Registered projects: {known or '(none)'}."
                ) from exc
            resolved.append(fallback_id)
            continue
        assert ident is not None
        resolved.append(int(ident.id))
    return resolved


def parse_project_cli_arg(arg: Optional[str]) -> Optional[List[str]]:
    """Parse a ``--project`` CLI value into a list of project refs.

    - ``None``, empty, or whitespace-only input returns ``None`` (no override).
    - Whitespace around each comma-separated slug/id is stripped.
    - Empty segments (e.g. trailing commas) are dropped.
    - A non-empty result is always a list of cleaned refs.
    """
    if arg is None:
        return None
    pieces = [piece.strip() for piece in arg.split(",")]
    cleaned = [piece for piece in pieces if piece]
    if not cleaned:
        return None
    return cleaned


def _list_registered_project_ids(conn: Any) -> List[int]:
    """Return registered project ids. Defensive against missing
    ``projects`` table: returns ``[1]`` as the default-project fallback when
    the table is absent (test DBs that exercise the session/claim surface
    without a full project registry stay functional).

    The missing-table swallow fires on both backends: SQLite and the Postgres
    facade raise different operational error classes, and Postgres aborts the
    transaction. The except uses
    ``operational_error_types(conn)`` and rolls back so the caller can keep
    using the same connection after the fallback.
    """
    try:
        rows = conn.execute(
            "SELECT id FROM projects ORDER BY id"
        ).fetchall()
    except db_backend.operational_error_types(conn):
        # On Postgres the missing-table error aborts the transaction; roll back
        # so the caller can keep using the same connection. SQLite does not
        # poison the transaction on a failed read, and a rollback there would
        # discard the caller's uncommitted writes — so this is Postgres-only.
        if db_backend.connection_is_postgres(conn):
            try:
                conn.rollback()
            except Exception:
                pass
        return [1]
    return [int(row_value(row, "id", 0)) for row in rows]


def _list_registered_project_refs(conn: Any) -> List[str]:
    try:
        rows = conn.execute("SELECT id, slug FROM projects ORDER BY id").fetchall()
    except db_backend.operational_error_types(conn):
        if db_backend.connection_is_postgres(conn):
            try:
                conn.rollback()
            except Exception:
                pass
        return ["1/yoke"]
    return [
        f"{row_value(row, 'id', 0)}/{row_value(row, 'slug', 1)}"
        for row in rows
    ]


def _fallback_project_id(project: str | int) -> Optional[int]:
    text = str(project).strip()
    if text == "1" or text == "yoke":
        return 1
    return int(text) if text.isdigit() and int(text) == 1 else None


__all__ = ["resolve_session_project_scope", "parse_project_cli_arg"]
