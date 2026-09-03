"""Registered handlers for the machine registry."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.machine_registry import (
    MachineRegistryError,
    list_machines,
    register_machine,
    require_machine,
    set_machine_access,
)
from yoke_core.domain.session_relay_storage import utc_now


class MachineRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_id: str
    name: str
    proof_public_key: str
    access: Optional[Dict[str, Any]] = None
    rotate_key: bool = False


class MachineRecordResponse(BaseModel):
    machine: Dict[str, Any]
    created: bool = False


class MachineListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owned_only: bool = False


class MachineListResponse(BaseModel):
    machines: List[Dict[str, Any]]
    count: int


class MachineShowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_id: str


class MachineSettingsGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_id: str
    path: Optional[str] = None


class MachineSettingsGetResponse(BaseModel):
    machine_id: str
    path: str
    value: Any


class MachineSettingsSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_id: str
    path: str
    value: Any


def _failure(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath="$.payload"),
    )


def _parse(model: Any, request: FunctionCallRequest) -> Any:
    try:
        return model.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - reported as a typed refusal
        return _failure("payload_invalid", str(exc))


def _actor_id(request: FunctionCallRequest) -> int:
    raw = str(request.actor.actor_id or "").strip()
    if not raw.isdigit():
        raise MachineRegistryError(
            "actor_required", "a verified numeric actor is required"
        )
    return int(raw)


def _open() -> Any:
    from yoke_core.domain.db_helpers import connect

    return connect()


def _is_admin(conn: Any, actor_id: int) -> bool:
    """Administer standing is org-wide here: a machine is not project-scoped."""
    from yoke_core.domain.actor_permissions import PERM_ORG_ADMIN
    from yoke_core.domain.machine_registry import marker

    p = marker(conn)
    row = conn.execute(
        "SELECT 1 FROM actor_org_roles aor "
        "JOIN roles r ON r.id = aor.role_id "
        "JOIN role_permissions rp ON rp.role_id = r.id "
        "JOIN permissions perm ON perm.id = rp.permission_id "
        f"WHERE aor.actor_id = {p} AND perm.key = {p} LIMIT 1",
        (int(actor_id), PERM_ORG_ADMIN),
    ).fetchone()
    return row is not None


def _project(document: Any, path: str) -> Any:
    """Read one dotted leaf out of an access document."""
    cursor: Any = document
    for segment in path.split("."):
        if not isinstance(cursor, dict) or segment not in cursor:
            raise MachineRegistryError(
                "machine_settings_path_unknown",
                f"access document has no {path!r}. Recovery: read the whole "
                "document with `yoke machine settings get MACHINE-ID`.",
            )
        cursor = cursor[segment]
    return cursor


def _assigned(document: Dict[str, Any], path: str, value: Any) -> Dict[str, Any]:
    """Return the document with one dotted leaf replaced."""
    segments = path.split(".")
    updated = {
        key: dict(inner) if isinstance(inner, dict) else inner
        for key, inner in document.items()
    }
    cursor: Any = updated
    for segment in segments[:-1]:
        if not isinstance(cursor, dict) or segment not in cursor:
            raise MachineRegistryError(
                "machine_settings_path_unknown",
                f"access document has no {path!r}",
            )
        cursor = cursor[segment]
    if not isinstance(cursor, dict) or segments[-1] not in cursor:
        raise MachineRegistryError(
            "machine_settings_path_unknown",
            f"access document has no {path!r}",
        )
    cursor[segments[-1]] = value
    return updated


def _refused(exc: Exception) -> HandlerOutcome:
    if isinstance(exc, MachineRegistryError):
        return _failure(exc.code, str(exc))
    return _failure("machine_registry_rejected", str(exc))


def handle_machine_register(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parse(MachineRegisterRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    conn = _open()
    try:
        actor_id = _actor_id(request)
        record, created = register_machine(
            conn,
            machine_id=parsed.machine_id,
            name=parsed.name,
            actor_id=actor_id,
            public_key=parsed.proof_public_key,
            access=parsed.access,
            is_admin=_is_admin(conn, actor_id),
            rotate_key=parsed.rotate_key,
            now=utc_now(),
        )
        return HandlerOutcome(
            result_payload={"machine": record.to_dict(), "created": created}
        )
    except Exception as exc:  # noqa: BLE001 - reported as a typed refusal
        return _refused(exc)
    finally:
        conn.close()


def handle_machine_list(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parse(MachineListRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    conn = _open()
    try:
        owner = _actor_id(request) if parsed.owned_only else None
        records = list_machines(conn, owner_actor_id=owner)
        return HandlerOutcome(
            result_payload={
                "machines": [record.to_dict() for record in records],
                "count": len(records),
            }
        )
    except Exception as exc:  # noqa: BLE001 - reported as a typed refusal
        return _refused(exc)
    finally:
        conn.close()


def handle_machine_show(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parse(MachineShowRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    conn = _open()
    try:
        record = require_machine(conn, parsed.machine_id)
        return HandlerOutcome(result_payload={"machine": record.to_dict()})
    except Exception as exc:  # noqa: BLE001 - reported as a typed refusal
        return _refused(exc)
    finally:
        conn.close()


def handle_machine_settings_get(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parse(MachineSettingsGetRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    conn = _open()
    try:
        record = require_machine(conn, parsed.machine_id)
        path = (parsed.path or "").strip()
        value = _project(record.access, path) if path else record.access
        return HandlerOutcome(
            result_payload={
                "machine_id": record.machine_id,
                "path": path,
                "value": value,
            }
        )
    except Exception as exc:  # noqa: BLE001 - reported as a typed refusal
        return _refused(exc)
    finally:
        conn.close()


def handle_machine_settings_set(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = _parse(MachineSettingsSetRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    conn = _open()
    try:
        actor_id = _actor_id(request)
        record = require_machine(conn, parsed.machine_id)
        updated = set_machine_access(
            conn,
            machine_id=record.machine_id,
            access=_assigned(record.access, parsed.path.strip(), parsed.value),
            actor_id=actor_id,
            is_admin=_is_admin(conn, actor_id),
            now=utc_now(),
        )
        return HandlerOutcome(result_payload={"machine": updated.to_dict()})
    except Exception as exc:  # noqa: BLE001 - reported as a typed refusal
        return _refused(exc)
    finally:
        conn.close()


__all__ = [
    "MachineListRequest",
    "MachineListResponse",
    "MachineRecordResponse",
    "MachineRegisterRequest",
    "MachineSettingsGetRequest",
    "MachineSettingsGetResponse",
    "MachineSettingsSetRequest",
    "MachineShowRequest",
    "handle_machine_list",
    "handle_machine_register",
    "handle_machine_settings_get",
    "handle_machine_settings_set",
    "handle_machine_show",
]
