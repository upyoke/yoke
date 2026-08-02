"""Author and project attribution for field-note writes.

Every field-note row records who logged it and which project it belongs
to. Both facts are resolved from the calling session at write time:

- **author** — the dispatched subagent role when the caller supplies one
  (``actor_role``, the same vocabulary tool-call telemetry uses for
  ``engineer`` / ``tester`` / ``architect`` / ...), otherwise the
  session's executor id, otherwise :data:`DEFAULT_AUTHOR`. This matches
  the role names the learning log has always carried in
  ``ouroboros_entries.agent``.
- **project** — the calling session's project scope, projected to its
  slug so the entry insert can reuse its existing ``project`` parameter.
  Without it the whole channel lands unattributed and cannot be sliced
  per project, which also blocks promotion (a note with no project has
  no target to promote into).

Neither falls back to the process working directory: the write handler
runs inside the server, where the calling checkout is not observable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import row_value


# Used when the caller has no resolvable session and names no role.
DEFAULT_AUTHOR = "agent"

# Harness adapters name a dispatched subagent `yoke-engineer`; the
# learning log keys the bare role.
_ROLE_PREFIX = "yoke-"


@dataclass(frozen=True)
class FieldNoteProvenance:
    """Resolved author label and project slug for one field-note write."""

    author: str
    project: Optional[str]


def _placeholder(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def normalize_actor_role(actor_role: Optional[str]) -> Optional[str]:
    """Bare role name for a dispatched subagent, or ``None``."""
    role = str(actor_role or "").strip().lower()
    if not role:
        return None
    if role.startswith(_ROLE_PREFIX):
        role = role[len(_ROLE_PREFIX) :]
    return role or None


def resolve_provenance(
    conn: Any,
    *,
    actor_role: Optional[str] = None,
    session_id: Optional[str] = None,
) -> FieldNoteProvenance:
    """Resolve the author label and project slug for a field-note write."""
    role = normalize_actor_role(actor_role)
    executor: Optional[str] = None
    project: Optional[str] = None

    if session_id:
        p = _placeholder(conn)
        row = conn.execute(
            "SELECT s.executor, p.slug FROM harness_sessions s "
            "LEFT JOIN projects p ON p.id = s.project_id "
            f"WHERE s.session_id = {p}",
            (str(session_id),),
        ).fetchone()
        if row is not None:
            executor = str(row_value(row, "executor", 0) or "").strip() or None
            project = str(row_value(row, "slug", 1) or "").strip() or None

    return FieldNoteProvenance(
        author=role or executor or DEFAULT_AUTHOR,
        project=project,
    )


__all__ = [
    "DEFAULT_AUTHOR",
    "FieldNoteProvenance",
    "normalize_actor_role",
    "resolve_provenance",
]
