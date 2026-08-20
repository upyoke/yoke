"""Author and project attribution for field-note writes.

Every field-note row records who logged it and which project it belongs
to. Attribution is resolved at write time:

- **author** — the dispatched subagent role when the caller supplies one
  (``actor_role``, the same vocabulary tool-call telemetry uses for
  ``engineer`` / ``tester`` / ``architect`` / ...), otherwise the
  session's executor id, otherwise :data:`DEFAULT_AUTHOR`. This matches
  the role names the learning log has always carried in
  ``ouroboros_entries.agent``. Session provenance for the author is
  always retained even when the project comes from the checkout.
- **project** — where the note was observed. Prefer a client-supplied
  registered checkout project (the CLI resolves ``$YOKE_PROJECT`` / the
  machine-config checkout→project map and carries the hint on the
  payload), then the calling session's project scope. Resolution keeps
  the ``projects`` row's slug and its id together as one unit, so the
  durable entry and its telemetry event name the same project instead of
  each re-resolving a slug that a multi-project universe can answer
  differently. Without either, the channel lands unattributed — the same
  global/no-checkout behavior as before.
- **target_project** — where the fix belongs, when the author says so.
  Never inferred: a note observed from one checkout routinely describes a
  defect that deploys from another, and only the author can tell the two
  apart. Absent, promotion falls back to the observing project.

The write handler never resolves an ambient cwd: it runs inside the
server, where the calling checkout is not observable. Checkout awareness
is a client-side resolution that arrives as an explicit project hint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Union

from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import (
    ProjectIdentity,
    resolve_project,
    row_value,
)


# Used when the caller has no resolvable session and names no role.
DEFAULT_AUTHOR = "agent"

# Harness adapters name a dispatched subagent `yoke-engineer`; the
# learning log keys the bare role.
_ROLE_PREFIX = "yoke-"


@dataclass(frozen=True)
class FieldNoteProvenance:
    """Resolved author label and project identity for one field-note write."""

    author: str
    project: Optional[str]
    project_id: Optional[int] = None
    target_project: Optional[str] = None


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


def _project_from_hint(
    conn: Any,
    project: Optional[Union[str, int]],
) -> Optional[ProjectIdentity]:
    """Resolve a client checkout project hint to one ``projects`` row.

    Raises ``LookupError`` when the hint is non-empty but names no
    projects row — isolation refuses a silent fallthrough to the session
    project when the client already named a specific checkout.
    """
    if project is None:
        return None
    cleaned = str(project).strip()
    if not cleaned:
        return None
    ident = resolve_project(conn, cleaned, required=True)
    assert ident is not None
    return ident


def _session_identity(
    conn: Any,
    session_id: str,
) -> tuple[Optional[str], Optional[str], Optional[int]]:
    """Executor label and project (slug, id) for the calling session.

    The join reads the slug and the id from the one ``projects`` row the
    session points at, so a session whose project row is gone attributes
    to nothing rather than to an id no project answers to.
    """
    p = _placeholder(conn)
    row = conn.execute(
        "SELECT s.executor, p.slug, p.id FROM harness_sessions s "
        "LEFT JOIN projects p ON p.id = s.project_id "
        f"WHERE s.session_id = {p}",
        (str(session_id),),
    ).fetchone()
    if row is None:
        return None, None, None
    project_id = row_value(row, "id", 2)
    return (
        str(row_value(row, "executor", 0) or "").strip() or None,
        str(row_value(row, "slug", 1) or "").strip() or None,
        int(project_id) if project_id is not None else None,
    )


def resolve_provenance(
    conn: Any,
    *,
    actor_role: Optional[str] = None,
    session_id: Optional[str] = None,
    project: Optional[Union[str, int]] = None,
    target_project: Optional[Union[str, int]] = None,
) -> FieldNoteProvenance:
    """Resolve the author label and project identity for a field-note write."""
    role = normalize_actor_role(actor_role)
    executor, session_project, session_project_id = (
        _session_identity(conn, session_id) if session_id else (None, None, None)
    )

    checkout = _project_from_hint(conn, project)
    observed_slug = checkout.slug if checkout is not None else session_project
    observed_id = checkout.id if checkout is not None else session_project_id
    declared_target = _project_from_hint(conn, target_project)

    return FieldNoteProvenance(
        author=role or executor or DEFAULT_AUTHOR,
        project=observed_slug,
        project_id=observed_id,
        target_project=(
            declared_target.slug if declared_target is not None else None
        ),
    )


__all__ = [
    "DEFAULT_AUTHOR",
    "FieldNoteProvenance",
    "normalize_actor_role",
    "resolve_provenance",
]
