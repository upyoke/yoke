"""Identity resolution and upgrade probes for hook-runner registration."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_contracts.session_level import level_is_unresolved


def project_level_for_session(
    conn: Any,
    project_id: Any,
    executor: str,
    *,
    explicit_level: Optional[str] = None,
    model: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
) -> Optional[str]:
    """Resolve this session's level from the levels its project reads.

    The levels are shared authority (the project's ``session-routing``
    override, else the universe definition), so the level is resolved here
    — at stamp time, against the connection about to write the row — rather
    than trusted from whatever the caller carried in. Returns ``None`` only
    without a project.

    ``model`` and ``reasoning_effort`` are what the session serves, matched
    against each level's options.
    """
    if project_id is None:
        return None
    from yoke_core.api.routing_config import resolve_execution_level, session_levels

    return resolve_execution_level(
        executor=executor,
        explicit_level=explicit_level,
        levels=session_levels(conn, project_id),
        model=model,
        reasoning_effort=reasoning_effort,
    )


def _wire_level(payload_json: str) -> str:
    """Return the level the hook payload carried, or ``""``."""
    if not payload_json:
        return ""
    payload = json.loads(payload_json)
    if not isinstance(payload, dict):
        return ""
    level = payload.get("execution_level", "")
    return level.strip() if isinstance(level, str) else ""


_LABEL_FACT_COLUMNS = (
    "model",
    "requested_model",
    "reasoning_effort",
    "requested_reasoning_effort",
)


def _level_can_upgrade(
    conn: Any,
    payload_json: str,
    session_id: str,
    project_id: Any,
) -> bool:
    """True when a stored level left unresolved can heal to a real one.

    The stored level is the authority the offer gate reads, so a row holding
    the unresolved sentinel is unroutable until something re-resolves it.
    Registration is idempotent and already upgrades an unresolved stored level
    in place, so reporting True lets any hook event repair the row. Two
    sources can supply the replacement: a level the payload carried, and the
    levels the project reads matched against the row's executor and model —
    the authority that outlives whatever the caller knew. Once the row carries a
    real level this returns False, which keeps a healed session from
    re-registering on every event.
    """
    try:
        from yoke_core.domain import db_backend

        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT execution_level, executor, model, requested_model, "
            "reasoning_effort, requested_reasoning_effort "
            f"FROM harness_sessions "
            f"WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
        if row is None:
            return False
        if hasattr(row, "get"):
            stored, executor = row.get("execution_level"), row.get("executor")
        else:
            stored, executor = row[0], row[1]
        if not level_is_unresolved(stored):
            return False
        if not level_is_unresolved(_wire_level(payload_json)):
            return True
        if not executor:
            return False
        from yoke_core.api.routing_config import routing_effort_of, routing_model_of

        values = (
            [row.get(key) for key in _LABEL_FACT_COLUMNS]
            if hasattr(row, "get")
            else list(row[2:6])
        )
        return not level_is_unresolved(
            project_level_for_session(
                conn,
                project_id,
                executor,
                model=routing_model_of(values[0], values[1]),
                reasoning_effort=routing_effort_of(values[2], values[3]),
            )
        )
    except Exception:  # noqa: BLE001 - probe must never break dispatch
        return False


def _model_facts_can_upgrade(
    conn: Any,
    payload_json: str,
    session_id: str,
) -> bool:
    """True when the wire's model facts say something the row does not.

    The served columns take the newest attestation, so a differing served
    value always qualifies — a session that switched model or effort
    mid-run is currently serving the later one. The requested columns fill
    a gap only. Once the row already says everything the wire knows this
    returns False, which keeps a settled session from re-registering on
    every event.
    """
    try:
        if not payload_json:
            return False
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            return False
        from yoke_contracts.session_model_facts import facts_from_mapping
        from yoke_core.hooks.registration_observed import (
            reclassify_unservable_model,
        )
        from yoke_core.domain import db_backend
        from yoke_core.domain.session_model_columns import (
            MODEL_COLUMNS,
            changed_columns,
        )

        incoming = reclassify_unservable_model(facts_from_mapping(payload))
        if not any(getattr(incoming, field) for field in MODEL_COLUMNS):
            # The wire said nothing about the model, so there is nothing to
            # compare and no reason to spend a query finding that out.
            return False
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT " + ", ".join(MODEL_COLUMNS) + " FROM harness_sessions "
            f"WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
        if row is None:
            return False
        columns, _values = changed_columns(row, incoming)
        return bool(columns)
    except Exception:  # noqa: BLE001 - probe must never break dispatch
        return False


def _executor_version_can_upgrade(
    conn: Any,
    payload_json: str,
    session_id: str,
) -> bool:
    """True when a surface-qualified wire version can fill a stored gap."""
    try:
        payload = json.loads(payload_json) if payload_json else {}
        if not isinstance(payload, dict):
            return False
        wire_version = payload.get("executor_version", "")
        wire_surface = payload.get("entrypoint", "")
        if (
            not isinstance(wire_version, str)
            or not wire_version.strip()
            or not isinstance(wire_surface, str)
            or not wire_surface.strip()
        ):
            return False
        from yoke_core.domain import db_backend

        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT executor_surface, executor_version FROM harness_sessions "
            f"WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
        if row is None:
            return False
        if hasattr(row, "get"):
            stored_surface = row.get("executor_surface")
            stored_version = row.get("executor_version")
        else:
            stored_surface, stored_version = row[0], row[1]
        surface = str(stored_surface or "").strip()
        return not str(stored_version or "").strip() and (
            not surface or surface == wire_surface.strip()
        )
    except Exception:  # noqa: BLE001 - probe must never break dispatch
        return False


def _executor_surface_can_upgrade(
    conn: Any,
    payload_json: str,
    session_id: str,
) -> bool:
    """True when hook-side resolution can name a missing stored surface."""
    try:
        payload = json.loads(payload_json) if payload_json else {}
        if not isinstance(payload, dict):
            return False
        wire_surface = payload.get("entrypoint", "")
        if not isinstance(wire_surface, str) or not wire_surface.strip():
            return False
        from yoke_core.domain import db_backend

        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT executor_surface FROM harness_sessions WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
        if row is None:
            return False
        stored = row.get("executor_surface") if hasattr(row, "get") else row[0]
        return not str(stored or "").strip()
    except Exception:  # noqa: BLE001 - probe must never break dispatch
        return False


def placeholder_identity_can_upgrade(
    conn: Any,
    payload_json: str,
    session_id: str,
    project_id: Any = None,
) -> bool:
    """True when identity resolution can improve the stored row.

    Model facts and level heal from different authorities: the facts ride
    the wire from the client that can read the harness artifact, while the
    level's last word is the levels the project reads, which only the
    control plane can read.
    """
    return (
        _model_facts_can_upgrade(
            conn,
            payload_json,
            session_id,
        )
        or _executor_version_can_upgrade(
            conn,
            payload_json,
            session_id,
        )
        or _executor_surface_can_upgrade(
            conn,
            payload_json,
            session_id,
        )
        or _level_can_upgrade(conn, payload_json, session_id, project_id)
    )


__all__ = ["placeholder_identity_can_upgrade", "project_level_for_session"]
