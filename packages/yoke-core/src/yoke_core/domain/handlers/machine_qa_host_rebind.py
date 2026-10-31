"""Record the current public address proved by a cloud host's lease holder."""

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.machine_config.test_machine import TestMachineCapabilityError
from yoke_core.domain import db_helpers
from yoke_core.domain.coordination_claims import active_claim
from yoke_core.domain.events import emit_event
from yoke_core.domain.handlers.machine_qa import _failure, _invalid
from yoke_core.domain.machine_qa_capability import host_claim_target
from yoke_core.domain.machine_qa_golden_destination import selected_test_machine_row
from yoke_core.domain.machine_qa_proven_settings import replace_proven_settings


class HostRebindRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str
    test_machine: str
    host: str
    base_settings: str


class HostRebindResponse(BaseModel):
    test_machine: str
    host: str


def handle_host_rebind(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = HostRebindRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _invalid(exc)
    conn = db_helpers.connect()
    try:
        row = selected_test_machine_row(
            conn, project=parsed.project, test_machine=parsed.test_machine
        )
        lease = active_claim(conn, host_claim_target(row.test_machine), for_update=True)
        if (
            lease is None
            or not request.actor.session_id
            or lease.session_id != request.actor.session_id
        ):
            return _failure(
                "test_machine_host_lease_required",
                "Only the session holding this Test Machine's active QA_HOST lease "
                "can rebind its host; run the case or golden operation under its lease.",
            )
        if not row.settings.get("cloud_instance_id"):
            return _failure(
                "test_machine_cloud_instance_required",
                "This Test Machine has no cloud_instance_id; register its cloud instance before rebinding.",
            )
        updates = {"host": parsed.host}
        if row.settings.get("desktop_host") == row.settings["host"]:
            updates["desktop_host"] = parsed.host
        if row.settings_token != parsed.base_settings or not replace_proven_settings(
            conn, row, updates
        ):
            return _failure(
                "test_machine_settings_changed",
                "Test Machine settings changed; re-read test_machine.get and retry with its settings_token.",
            )
        emit_event(
            "test_machine.host_rebound",
            event_kind="lifecycle",
            event_type="test_machine",
            project=row.project,
            session_id=request.actor.session_id,
            context={
                "test_machine": row.test_machine,
                "cloud_instance_id": row.settings["cloud_instance_id"],
                "previous_host": row.settings["host"],
                "host": parsed.host,
            },
            conn=conn,
            transactional=True,
        )
        conn.commit()
        return HandlerOutcome(
            primary_success=True,
            result_payload={
                "test_machine": row.test_machine,
                "host": parsed.host,
            },
        )
    except TestMachineCapabilityError as exc:
        conn.rollback()
        return _failure("test_machine_settings_invalid", str(exc))
    finally:
        conn.close()
