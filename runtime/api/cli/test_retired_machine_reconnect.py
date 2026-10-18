"""A retired computer reconnects under a new machine identity, without reinstalling."""

from __future__ import annotations

from collections import deque
import json
import uuid

import pytest

from yoke_cli.config import hosted_machine_authorization as auth
from yoke_cli.config import machine_config_mutation, machine_registration
from yoke_cli.config import onboard_machine_registry
from yoke_cli.transport.bounded_json_http import (
    BoundedJsonHttpResponse,
    BoundedJsonHttpStatusError,
)
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_contracts.machine_config import schema as contract

from runtime.api.fixtures.machine_config_test import select_machine_config_file


RETIRED_ID = "0b6f3f4e-41d5-4c3e-9e57-2f1f0c3d9a11"
STARTED = {
    "device_code": "device-secret",
    "user_code": "ABCD-2345",
    "verification_uri": "https://app.upyoke.com/connect",
    "verification_uri_complete": "https://app.upyoke.com/connect?user_code=ABCD-2345",
    "expires_in": 60,
    "interval": 1,
}


def _retired() -> BoundedJsonHttpStatusError:
    return BoundedJsonHttpStatusError(
        409, {"error": "machine_retired", "message": "machine is retired"}
    )


@pytest.fixture()
def config_path(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {"schema_version": contract.SCHEMA_VERSION, "machine_id": RETIRED_ID}
        ),
        encoding="utf-8",
    )
    select_machine_config_file(monkeypatch, str(path))
    monkeypatch.setattr(auth, "machine_display_name", lambda: "Build Host")
    return path


def _configured_id(path) -> str:
    return json.loads(path.read_text(encoding="utf-8"))["machine_id"]


def _serve(monkeypatch, *replies) -> list[dict]:
    queue, sent = deque(replies), []

    def fake_request(request, **_kwargs):
        sent.append(json.loads(request.data))
        reply = queue.popleft()
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(auth, "request_json", fake_request)
    return sent


def test_start_replaces_a_retired_identity_once_and_requests_a_fresh_code(
    monkeypatch, config_path
):
    sent = _serve(
        monkeypatch,
        _retired(),
        BoundedJsonHttpResponse(payload=STARTED, status=200, headers={}),
    )
    pending = auth.start("https://app.upyoke.com")
    replacement = _configured_id(config_path)
    assert replacement != RETIRED_ID and str(uuid.UUID(replacement)) == replacement
    assert [body["machine_id"] for body in sent] == [RETIRED_ID, replacement]
    assert pending.retired_machine_id == RETIRED_ID
    assert pending.user_code == "ABCD-2345"


def test_a_second_retired_refusal_stops_by_name(monkeypatch, config_path):
    sent = _serve(monkeypatch, _retired(), _retired())
    with pytest.raises(auth.HostedMachineAuthorizationError) as excinfo:
        auth.start("https://app.upyoke.com")
    assert str(excinfo.value).startswith("machine_retired:")
    assert "inspect its machine registry" in str(excinfo.value)
    assert len(sent) == 2


def test_other_start_refusals_keep_this_computers_identity(monkeypatch, config_path):
    _serve(
        monkeypatch,
        BoundedJsonHttpStatusError(
            403, {"error": "actor_disabled", "message": "ask an admin"}
        ),
    )
    with pytest.raises(auth.HostedMachineAuthorizationError):
        auth.start("https://app.upyoke.com")
    assert _configured_id(config_path) == RETIRED_ID


def test_retired_at_delivery_swaps_identity_and_names_the_next_step(
    monkeypatch, config_path
):
    # An older server issues the code and refuses only at credential delivery.
    _serve(
        monkeypatch,
        BoundedJsonHttpStatusError(
            403, {"error": "machine_retired", "message": "machine is retired"}
        ),
    )
    pending = auth.PendingMachineAuthorization(
        platform_url="https://app.upyoke.com", **STARTED
    )
    with pytest.raises(auth.HostedMachineAuthorizationError) as excinfo:
        auth.complete(pending, sleep=lambda _s: None, monotonic=lambda: 0.0)
    assert str(excinfo.value).startswith("machine_retired:")
    assert "run `yoke connect` again" in str(excinfo.value)
    assert _configured_id(config_path) != RETIRED_ID


def test_replacement_keeps_an_identity_another_connect_already_swapped_in(
    config_path,
):
    first = machine_config_mutation.replace_retired_machine_identity(RETIRED_ID)
    again = machine_config_mutation.replace_retired_machine_identity(RETIRED_ID)
    assert first == again == _configured_id(config_path) != RETIRED_ID


def _register_reply(*, retired: bool, machine_id: str = "") -> FunctionCallResponse:
    if retired:
        return FunctionCallResponse(
            success=False,
            function="machine.register",
            version="v1",
            error=FunctionError(code="machine_retired", message="retired"),
        )
    return FunctionCallResponse(
        success=True,
        function="machine.register",
        version="v1",
        result={"machine": {"machine_id": machine_id, "name": "Build Host"}},
    )


def test_local_registration_replaces_a_retired_identity_once(monkeypatch, config_path):
    calls: list[str] = []

    def fake_register(payload):
        calls.append(payload["machine_id"])
        return _register_reply(
            retired=payload["machine_id"] == RETIRED_ID,
            machine_id=payload["machine_id"],
        )

    monkeypatch.setattr(machine_registration, "_call_register", fake_register)
    monkeypatch.setattr(machine_registration, "_persist_credential", lambda *_: None)
    outcome = machine_registration.register_this_machine(config_path)
    replacement = _configured_id(config_path)
    assert calls == [RETIRED_ID, replacement]
    assert outcome["registered"] is True
    assert outcome["machine_id"] == replacement
    assert outcome["retired_machine_id"] == RETIRED_ID
    (line,) = onboard_machine_registry.summary_lines(outcome)
    assert RETIRED_ID in line and "new machine identity" in line


def test_local_registration_reports_a_foreign_owner_without_swapping(
    monkeypatch, config_path
):
    refusal = FunctionCallResponse(
        success=False,
        function="machine.register",
        version="v1",
        error=FunctionError(code="machine_owner_mismatch", message="other owner"),
    )
    monkeypatch.setattr(machine_registration, "_call_register", lambda _p: refusal)
    outcome = machine_registration.register_this_machine(config_path)
    assert outcome["registered"] is False
    assert outcome["reason"] == "machine_owner_mismatch: other owner"
    assert _configured_id(config_path) == RETIRED_ID
