"""Identity resolution and upgrade probes for hook-runner registration."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_contracts.session_lane import lane_is_unresolved


def project_lane_for_executor(
    conn: Any,
    project_id: Any,
    executor: str,
    *,
    explicit_lane: Optional[str] = None,
) -> Optional[str]:
    """Resolve ``executor``'s lane from the project's routing policy.

    Routing policy is project-scoped shared authority (the
    ``session-routing`` capability), so the lane is resolved here — at stamp
    time, against the connection that is about to write the row — rather
    than trusted from whatever the caller carried in. Returns ``None`` when
    the project declares no routing policy, leaving the caller's own
    fallback in charge.
    """
    if project_id is None:
        return None
    from yoke_core.api.routing_config import (
        load_project_routing_settings,
        load_routing_config,
        resolve_execution_lane,
    )

    settings = load_project_routing_settings(conn, project_id)
    if not settings:
        return None
    return resolve_execution_lane(
        executor=executor,
        explicit_lane=explicit_lane,
        # Project settings are the complete routing authority; the machine
        # config path is unread whenever they are supplied.
        routing_config=load_routing_config("", project_settings=settings),
    )


def _wire_lane(payload_json: str) -> str:
    """Return the lane the hook payload carried, or ``""``."""
    if not payload_json:
        return ""
    payload = json.loads(payload_json)
    if not isinstance(payload, dict):
        return ""
    lane = payload.get("execution_lane", "")
    return lane.strip() if isinstance(lane, str) else ""


def _lane_can_upgrade(
    conn: Any,
    payload_json: str,
    session_id: str,
    project_id: Any,
) -> bool:
    """True when a stored lane left unresolved can heal to a real one.

    The stored lane is the authority the offer gate reads, so a row holding
    the unresolved sentinel is unroutable until something re-resolves it.
    Registration is idempotent and already upgrades an unresolved stored lane
    in place, so reporting True lets any hook event repair the row. Two
    sources can supply the replacement: a lane the payload carried, and the
    project's own routing policy resolved against the row's executor — the
    authority that outlives whatever the caller knew. Once the row carries a
    real lane this returns False, which keeps a healed session from
    re-registering on every event.
    """
    try:
        from yoke_core.domain import db_backend

        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT execution_lane, executor FROM harness_sessions "
            f"WHERE session_id = {p}",
            (session_id,),
        ).fetchone()
        if row is None:
            return False
        if hasattr(row, "get"):
            stored, executor = row.get("execution_lane"), row.get("executor")
        else:
            stored, executor = row[0], row[1]
        if not lane_is_unresolved(stored):
            return False
        if not lane_is_unresolved(_wire_lane(payload_json)):
            return True
        if not executor:
            return False
        return not lane_is_unresolved(
            project_lane_for_executor(conn, project_id, executor)
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
        from yoke_core.domain import db_backend
        from yoke_core.domain.session_model_columns import (
            MODEL_COLUMNS,
            changed_columns,
        )

        incoming = _without_placeholder_model(facts_from_mapping(payload))
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


def _without_placeholder_model(facts):
    """Drop a placeholder served model: a placeholder is not an attestation.

    An older client can still put ``unknown`` on the wire, and storing that
    as the served model would assert a provider reported it.
    """
    from dataclasses import replace

    from yoke_harness.hooks.identity import _is_placeholder_model

    if facts.model is not None and _is_placeholder_model(facts.model):
        return replace(facts, model=None)
    return facts


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

    Model facts and lane heal from different authorities: the facts ride
    the wire from the client that can read the harness artifact, while the
    lane's last word is project routing policy, which only the control
    plane can read.
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
        or _lane_can_upgrade(conn, payload_json, session_id, project_id)
    )


__all__ = ["placeholder_identity_can_upgrade", "project_lane_for_executor"]
