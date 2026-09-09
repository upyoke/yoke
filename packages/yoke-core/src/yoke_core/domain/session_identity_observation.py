"""Persist what a finished turn proves about an existing session's identity.

Identity arrives the same two ways consumption does. A relayed hook carries
the reading its own machine took, because only that machine can see the
harness artifact. A local hook carries nothing, so the reading is taken
here — the same process, the same machine, the same artifact.

Registration is not that reader. A session registers before its first
response exists, so the model a provider served and the surface it was
served on are both unknown at the moment registration runs. Every later
healing path is keyed on the relayed wire, and the one local writer runs
from ``PreToolUse``. A single-turn answer that calls no tool therefore
reaches its last hook with native evidence nobody reads, and keeps NULL
for the rest of its life.

Reading an existing row is what makes that observation safe on a terminal
hook, where registration deliberately does not run: this writes served
facts onto a row that already exists and does nothing else. It never
inserts, never revives an ended session, and never touches lifecycle,
episode, claim, or usage state.

Two write rules keep the stored identity honest:

* Served model facts follow the newest-reading rule they follow everywhere
  (:mod:`yoke_core.domain.session_model_columns`), so repeated observation
  of the same turn is write-free.
* The surface fills a gap only. It names the process the session runs in,
  fixed for that session's life, so a later differing reading is a
  different reader rather than a change.

The requested columns are never written here. The ask was fixed when the
session was launched; this reader only ever sees what was served.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple

from yoke_contracts.session_model_facts import (
    SERVED_FIELDS,
    SessionModelFacts,
    facts_from_mapping,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_model_columns import MODEL_COLUMNS, changed_columns
from yoke_core.domain.sessions_lifecycle_canonicalize import canonicalize_executor


SURFACE_COLUMN = "executor_surface"


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _payload(payload_json: str) -> dict[str, Any]:
    import json

    try:
        parsed = json.loads(payload_json) if payload_json else {}
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


ROW_COLUMNS = (*MODEL_COLUMNS, SURFACE_COLUMN)


def _row_map(row: Any) -> dict[str, Any]:
    """Read one row as a column mapping, whichever row shape it is.

    A driver may hand back a mapping or a positional row, and reading a
    positional row by column name silently yields nothing — which here
    would look exactly like a row with no identity stored and invite an
    overwrite. The SELECT below fixes the column order, so the
    positional case is answerable rather than guessed at.
    """
    if hasattr(row, "keys"):
        return {column: row[column] for column in ROW_COLUMNS}
    return dict(zip(ROW_COLUMNS, row))


def _stored(row: dict[str, Any], column: str) -> str:
    return str(row.get(column) or "").strip()


def _served_only(facts: SessionModelFacts) -> SessionModelFacts:
    """Drop the requested half of a reading, which this reader never writes."""
    return SessionModelFacts(
        **{field: getattr(facts, field) for field in SERVED_FIELDS}
    )


def carried_served_facts(payload: dict[str, Any]) -> SessionModelFacts:
    """Return the served facts a relayed hook already resolved, if any."""
    from yoke_core.hooks.registration_observed import reclassify_unservable_model

    return _served_only(reclassify_unservable_model(facts_from_mapping(payload)))


def local_served_facts(payload: dict[str, Any], executor: str) -> SessionModelFacts:
    """Read the served facts this machine's own harness artifact proves."""
    if not executor:
        return SessionModelFacts()
    try:
        from yoke_harness.hooks.identity_relay import resolve_model_facts

        return _served_only(resolve_model_facts(payload, executor))
    except Exception:  # noqa: BLE001 — identity observation never breaks a hook
        return SessionModelFacts()


def resolve_surface(executor: str, entrypoint: str) -> Optional[str]:
    """Return the registry surface label ``executor`` + ``entrypoint`` name.

    ``None`` is the honest answer for an entrypoint token no harness
    registry recognizes; the column stays NULL rather than recording a
    surface nobody can read back.
    """
    if not executor or not entrypoint:
        return None
    try:
        return canonicalize_executor(executor, entrypoint)[1]
    except ValueError:
        return None


def observed_surface(payload: dict[str, Any], executor: str) -> Optional[str]:
    """Return the surface this hook event carries, or can resolve itself."""
    carried = payload.get("entrypoint")
    entrypoint = carried.strip() if isinstance(carried, str) else ""
    if not entrypoint and executor:
        try:
            from yoke_harness.hooks.identity_relay import client_entrypoint

            entrypoint = client_entrypoint(executor, payload) or ""
        except Exception:  # noqa: BLE001 — identity probes never break a hook
            entrypoint = ""
    return resolve_surface(executor, entrypoint)


def observed_identity(
    row: dict[str, Any], payload_json: str, executor: str
) -> Tuple[SessionModelFacts, Optional[str]]:
    """Return the served facts and surface worth writing onto ``row``.

    The wire's reading is free to consult and always consulted. The local
    artifact costs a file read, so it is taken only where the stored row
    still has the gap it would fill — which is exactly the case this
    reader exists for.
    """
    payload = _payload(payload_json)
    facts = carried_served_facts(payload)
    if not facts.attested() and not _stored(row, "model"):
        facts = local_served_facts(payload, executor)
    surface = None
    if not _stored(row, SURFACE_COLUMN):
        surface = observed_surface(payload, executor)
    return facts, surface


def record_session_identity(
    conn: Any,
    *,
    session_id: str,
    payload_json: str,
    executor: str = "",
) -> bool:
    """Store a newer identity reading; a repeated one stays write-free."""
    if conn is None or not session_id:
        return False
    marker = _marker(conn)
    fetched = conn.execute(
        "SELECT " + ", ".join(ROW_COLUMNS) + " "
        f"FROM harness_sessions WHERE session_id={marker}",
        (session_id,),
    ).fetchone()
    if fetched is None:
        return False
    row = _row_map(fetched)
    facts, surface = observed_identity(row, payload_json, executor)
    columns, values = changed_columns(row, facts)
    if surface:
        columns.append(SURFACE_COLUMN)
        values.append(surface)
    if not columns:
        return False
    assignments = ", ".join(f"{column}={marker}" for column in columns)
    conn.execute(
        f"UPDATE harness_sessions SET {assignments} WHERE session_id={marker}",
        (*values, session_id),
    )
    conn.commit()
    return True


__all__ = [
    "ROW_COLUMNS",
    "SURFACE_COLUMN",
    "carried_served_facts",
    "local_served_facts",
    "observed_identity",
    "observed_surface",
    "record_session_identity",
    "resolve_surface",
]
