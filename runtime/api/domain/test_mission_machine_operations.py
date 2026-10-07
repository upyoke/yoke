"""Host operations retain their mission's lease and reject foreign owners."""

import base64
import hashlib
from io import BytesIO

from PIL import Image
import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.test_agent_mission_qa import (
    ACTOR,
    _materialize_mission,
    _request,
)
from runtime.api.domain.test_machine_screenshot import screenshot_result
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.handlers.machine_qa_execution_abort import handle_operation_abort
from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.host_control_runner import (
    register_host_control_factory,
    clear_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import (
    execute_host_operation_contract,
    prepare_agent_mission_contract,
)
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_review import begin_plan_review


def request(payload, actor=ACTOR):
    return FunctionCallRequest(
        function="test_machine.operation",
        actor=actor,
        target=TargetRef(kind="global"),
        payload=payload,
    )


@pytest.fixture
def mission(test_db, tmp_path, monkeypatch):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    item_id = 4901
    requirement_id = _materialize_mission(test_db, item_id=item_id)
    execution = begin_plan_execution(
        test_db,
        item_id=item_id,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    execution_id = str(execution["id"])
    args = dict(
        item_id=item_id,
        execution_id=execution_id,
        requirement_id=requirement_id,
        ordinal=0,
    )
    begun = handle_plan_case_begin(_request("test_machine.plan_case.begin", **args))
    assert begun.primary_success, begun.error
    contract = begun.result_payload["execution"]
    control = FakeHostControl()
    control.capture_screenshot = screenshot_result
    register_host_control_factory(lambda _material: control)
    try:
        prepared = prepare_agent_mission_contract(contract)
        ready = handle_agent_mission_ready(
            _request("test_machine.mission.ready", **args, payload=prepared)
        )
        assert ready.primary_success, ready.error
        assert begin_plan_review(test_db, lock_plan_execution(test_db, execution_id))
        test_db.commit()
        monkeypatch.setattr(
            "yoke_core.domain.handlers.machine_qa_screenshot_artifact.store_owned_artifact_bytes",
            lambda conn, **kwargs: {
                "backend": "local",
                "path": str(tmp_path / "desktop.png"),
                "content_type": "image/png",
            },
        )
        yield test_db, contract, control, execution_id
    finally:
        clear_host_control_factory()


def begin(operation, actor=ACTOR):
    return handle_operation_begin(
        request(
            {
                "project": "yoke",
                "operation": operation,
                **(
                    {"destination": "/Users/Shared/yoke-golden/captured-home"}
                    if operation == "golden_capture"
                    else {}
                ),
            },
            actor,
        )
    )


def submit(contract):
    submission = execute_host_operation_contract(contract)
    return handle_operation_submit(
        request(
            {
                "project": "yoke",
                "destination": contract.get("golden_destination"),
                **submission.payload,
            }
        )
    )


@pytest.mark.parametrize("operation", ["golden_capture", "screenshot"])
def test_mission_holder_borrows_lease_and_submit_keeps_it(mission, operation):
    conn, mission_contract, control, execution_id = mission
    begun = begin(operation)
    assert begun.primary_success, begun.error
    contract = begun.result_payload["execution"]
    assert contract["lease_id"] == mission_contract["lease_id"]
    accepted = submit(contract)
    assert accepted.primary_success, accepted.error
    assert get_claim(conn, contract["lease_id"]).is_active
    execution = lock_plan_execution(conn, execution_id)
    assert execution["state"] == "awaiting_agent_review"
    assert execution["machine_lease_id"] == contract["lease_id"]
    conn.commit()
    if operation == "golden_capture":
        assert control.captured_destinations == [contract["golden_destination"]]
        assert (
            accepted.result_payload["golden_baseline_path"]
            == contract["golden_destination"]
        )
    else:
        assert accepted.result_payload["checks"][0]["artifact_handle"]
    replay = submit(contract)
    assert replay.primary_success, replay.error
    assert (
        replay.result_payload["performed_at"] == accepted.result_payload["performed_at"]
    )
    assert get_claim(conn, contract["lease_id"]).is_active


@pytest.mark.parametrize("operation", ["golden_capture", "screenshot"])
@pytest.mark.parametrize(
    "actor",
    [
        ActorContext(actor_id="2", session_id="foreign-session"),
        ActorContext(actor_id="1", session_id=ACTOR.session_id),
    ],
)
def test_foreign_session_or_actor_cannot_borrow_mission(mission, operation, actor):
    conn, contract, _, _ = mission
    refused = begin(operation, actor)
    assert not refused.primary_success
    assert "mission_operation_foreign_holder" in refused.error.message
    assert "ask its holder" in refused.error.message
    assert get_claim(conn, contract["lease_id"]).is_active


@pytest.mark.parametrize("operation", ["golden_capture", "screenshot"])
def test_operation_abort_retains_mission_lease(mission, operation):
    conn, _, _, _ = mission
    begun = begin(operation)
    assert begun.primary_success, begun.error
    contract = begun.result_payload["execution"]
    aborted = handle_operation_abort(
        request(
            {
                "project": "yoke",
                "operation": operation,
                "lease_id": contract["lease_id"],
                "contract_digest": contract["contract_digest"],
                "destination": contract.get("golden_destination"),
                "reason": "local_execution_failed",
            }
        )
    )
    assert aborted.primary_success, aborted.error
    assert aborted.result_payload["released"] is False
    assert get_claim(conn, contract["lease_id"]).is_active


@pytest.mark.parametrize("handler", [handle_operation_submit, handle_operation_abort])
def test_foreign_submission_or_abort_cannot_settle_mission(mission, handler):
    conn, _, _, _ = mission
    contract = begin("screenshot").result_payload["execution"]
    submission = execute_host_operation_contract(contract)
    payload = {"project": "yoke", **submission.payload}
    if handler == handle_operation_abort:
        payload = {
            key: payload[key]
            for key in ("project", "lease_id", "contract_digest", "operation")
        }
        payload["reason"] = "client_cancelled"
    refused = handler(
        request(payload, ActorContext(actor_id="2", session_id="foreign-session"))
    )
    assert not refused.primary_success
    assert "mission_operation_foreign_holder" in refused.error.message
    assert get_claim(conn, contract["lease_id"]).is_active


@pytest.mark.parametrize("handler", [handle_operation_submit, handle_operation_abort])
def test_unknown_lease_gets_diagnosed_refusal(test_db, tmp_path, monkeypatch, handler):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    payload = {
        "project": "yoke",
        "lease_id": 999999,
        "contract_digest": "missing",
        "operation": "screenshot",
    }
    if handler == handle_operation_abort:
        payload["reason"] = "client_cancelled"
    else:
        payload.update(
            status="error",
            checks=[{"name": "screenshot", "ok": False}],
            error_code="desktop_screenshot_failed",
        )
    refused = handler(request(payload))
    assert not refused.primary_success
    assert "was not issued" in refused.error.message


def test_later_mission_screenshot_can_replace_receipt(mission):
    _, _, control, _ = mission
    first = begin("screenshot").result_payload["execution"]
    assert submit(first).primary_success
    second = begin("screenshot").result_payload["execution"]
    original = screenshot_result

    def changed_frame():
        result = original()
        artifact = result.evidence["capture_artifact"]
        image = Image.open(BytesIO(base64.b64decode(artifact["content_base64"])))
        image.putpixel((1, 1), (255, 0, 0))
        stream = BytesIO()
        image.save(stream, format="PNG")
        content = stream.getvalue()
        artifact["content_base64"] = base64.b64encode(content).decode()
        result.evidence["sha256"] = hashlib.sha256(content).hexdigest()
        return result

    control.capture_screenshot = changed_frame
    accepted = submit(second)
    assert accepted.primary_success, accepted.error
    assert (
        accepted.result_payload["checks"][0]["sha256"]
        == changed_frame().evidence["sha256"]
    )


def test_nonmission_same_holder_still_requires_exclusive_admission(
    test_db, tmp_path, monkeypatch
):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    first = begin("screenshot")
    assert first.primary_success, first.error
    contract = first.result_payload["execution"]
    refused = begin("screenshot")
    assert not refused.primary_success
    assert "in use by another execution" in refused.error.message
    aborted = handle_operation_abort(
        request(
            {
                "project": "yoke",
                "operation": "screenshot",
                "lease_id": contract["lease_id"],
                "contract_digest": contract["contract_digest"],
                "reason": "client_cancelled",
            }
        )
    )
    assert aborted.primary_success, aborted.error
    assert aborted.result_payload["released"] is True
    assert not get_claim(test_db, contract["lease_id"]).is_active
