"""Registered machine credential, detail, and retirement handlers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers import machine_registry as common
from yoke_core.domain.machine_credentials import (
    register_with_credential,
    retire_with_credentials,
)
from yoke_core.domain.machine_registry import require_machine
from yoke_core.domain.session_relay_storage import utc_now


class MachineRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_id: str
    name: Optional[str] = None
    access: Optional[Dict[str, Any]] = None


class MachineRegisterResponse(common.MachineRecordResponse):
    credential: Dict[str, Any]


class MachineDetailResponse(common.OffersDisclosureResponse):
    machine: Dict[str, Any]
    relay: Optional[Dict[str, Any]] = None
    harnesses: List[Dict[str, Any]]
    projects: List[Dict[str, Any]]
    running_sessions: List[Dict[str, Any]]
    recent_sessions: List[Dict[str, Any]]
    recent_launches: List[Dict[str, Any]]
    surface_policies: List[Dict[str, Any]]
    token: Dict[str, Any]
    credential_presence: Dict[str, Any]


class MachineRetireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    machine_id: str


def handle_machine_register(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = common._parse(MachineRegisterRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    conn = common._open()
    try:
        actor_id = common._actor_id(request)
        record, created, credential = register_with_credential(
            conn,
            machine_id=parsed.machine_id,
            name=(parsed.name or parsed.machine_id),
            actor_id=actor_id,
            access=parsed.access,
            is_admin=common._is_admin(conn, actor_id),
            now=utc_now(),
        )
        return HandlerOutcome(
            result_payload=common._with_offers_disclosure(
                {
                    "machine": record.to_dict(),
                    "created": created,
                    "credential": credential.to_dict(),
                }
            )
        )
    except Exception as exc:  # noqa: BLE001 - typed function refusal
        return common._refused(exc)
    finally:
        conn.close()


def handle_machine_detail(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = common._parse(common.MachineShowRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    conn = common._open()
    try:
        from yoke_core.domain.machine_detail import machine_detail

        record = require_machine(conn, parsed.machine_id)
        return HandlerOutcome(
            result_payload=common._with_offers_disclosure(
                machine_detail(conn, record=record, actor_id=common._actor_id(request))
            )
        )
    except Exception as exc:  # noqa: BLE001 - typed function refusal
        return common._refused(exc)
    finally:
        conn.close()


def handle_machine_retire(request: FunctionCallRequest) -> HandlerOutcome:
    parsed = common._parse(MachineRetireRequest, request)
    if isinstance(parsed, HandlerOutcome):
        return parsed
    conn = common._open()
    try:
        actor_id = common._actor_id(request)
        record = retire_with_credentials(
            conn,
            machine_id=parsed.machine_id,
            actor_id=actor_id,
            is_admin=common._is_admin(conn, actor_id),
            now=utc_now(),
        )
        return HandlerOutcome(
            result_payload=common._with_offers_disclosure({"machine": record.to_dict()})
        )
    except Exception as exc:  # noqa: BLE001 - typed function refusal
        return common._refused(exc)
    finally:
        conn.close()


__all__ = [
    "MachineDetailResponse",
    "MachineRegisterRequest",
    "MachineRegisterResponse",
    "MachineRetireRequest",
    "handle_machine_detail",
    "handle_machine_register",
    "handle_machine_retire",
]
