"""Record one configured release pin through a narrow CAS mutation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from yoke_core.domain.db_helpers import connect, query_one
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.release_pin_capability import (
    CAPABILITY_TYPE,
    ReleasePinRoute,
    route_for_target,
)
from yoke_core.domain.settings_cas import (
    SettingsConflictError,
    apply_key_path_assignments,
    parse_settings_object,
    read_key_path,
)


class ReleasePinCapabilityMissing(LookupError):
    """The project has no release-pin routing declaration."""


class ReleasePinCapabilityInvalid(ValueError):
    """The release-pin declaration is incomplete or malformed."""


class ReleasePinTargetNotConfigured(LookupError):
    """The requested deploy target has no configured environment mapping."""


class ReleasePinProjectMismatch(ValueError):
    """The configured environment belongs to a different project."""


@dataclass(frozen=True)
class ReleasePinRecord:
    project: str
    environment: str
    environment_id: str
    settings_path: str
    pin: str
    changed: bool


def record_release_pin(
    project: str,
    environment: str,
    pin: str,
    *,
    db_path: Optional[str] = None,
) -> ReleasePinRecord:
    """Write only the path selected by the project's release-pin capability."""
    normalized_pin = _normalized_pin(pin)
    conn = connect(db_path)
    try:
        project_id = resolve_project_id(conn, project)
        route = _configured_route(conn, project_id, project, environment)
        for attempt in range(2):
            row = _environment_settings_row(conn, route.environment_id)
            if row is None:
                raise LookupError(
                    f"environment {route.environment_id!r} was not found"
                )
            if int(row["project_id"]) != project_id:
                raise ReleasePinProjectMismatch(
                    f"configured environment {route.environment_id!r} does "
                    f"not belong to project {project!r}"
                )
            base = str(row["settings"] or "{}")
            document = parse_settings_object(
                base, what=f"stored settings for {route.environment_id!r}"
            )
            if read_key_path(document, route.desired_pin_path) == normalized_pin:
                return _receipt(
                    project, environment, route, normalized_pin, changed=False
                )
            merged = json.dumps(
                apply_key_path_assignments(
                    document, {route.desired_pin_path: normalized_pin}
                )
            )
            cursor = conn.execute(
                "UPDATE environments SET settings=%s "
                "WHERE id=%s AND COALESCE(settings, '{}')=%s",
                (merged, route.environment_id, base),
            )
            if cursor.rowcount:
                conn.commit()
                return _receipt(
                    project, environment, route, normalized_pin, changed=True
                )
            conn.rollback()
            if attempt == 1:
                raise SettingsConflictError(
                    "settings_conflict: release-pin environment settings "
                    "changed during both compare-and-swap attempts"
                )
        raise AssertionError("release-pin CAS loop exhausted unexpectedly")
    finally:
        conn.close()


def _configured_route(
    conn: Any, project_id: int, project: str, environment: str
) -> ReleasePinRoute:
    row = query_one(
        conn,
        "SELECT settings FROM project_capabilities "
        "WHERE project_id=%s AND type=%s",
        (project_id, CAPABILITY_TYPE),
    )
    if row is None:
        raise ReleasePinCapabilityMissing(
            f"project {project!r} has no {CAPABILITY_TYPE!r} capability"
        )
    try:
        settings = json.loads(str(row["settings"] or "{}"))
        if not isinstance(settings, dict):
            raise ValueError("settings root must be an object")
        return route_for_target(settings, environment)
    except LookupError as exc:
        raise ReleasePinTargetNotConfigured(str(exc)) from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ReleasePinCapabilityInvalid(
            f"project {project!r} has invalid {CAPABILITY_TYPE!r} settings: {exc}"
        ) from exc


def _environment_settings_row(conn: Any, environment_id: str) -> Any:
    return query_one(
        conn,
        "SELECT s.project_id, COALESCE(e.settings, '{}') AS settings "
        "FROM environments e JOIN sites s ON s.id=e.site WHERE e.id=%s",
        (environment_id,),
    )


def _normalized_pin(pin: str) -> str:
    normalized = str(pin or "").strip()
    if not normalized:
        raise ValueError("pin must be a non-empty string")
    if len(normalized) > 200 or any(ord(char) < 32 for char in normalized):
        raise ValueError("pin must be at most 200 printable characters")
    return normalized


def _receipt(
    project: str,
    environment: str,
    route: ReleasePinRoute,
    pin: str,
    *,
    changed: bool,
) -> ReleasePinRecord:
    return ReleasePinRecord(
        project=project,
        environment=environment,
        environment_id=route.environment_id,
        settings_path=route.desired_pin_path,
        pin=pin,
        changed=changed,
    )


__all__ = [
    "ReleasePinCapabilityInvalid",
    "ReleasePinCapabilityMissing",
    "ReleasePinProjectMismatch",
    "ReleasePinRecord",
    "ReleasePinTargetNotConfigured",
    "record_release_pin",
]
