"""Relay functions require a bearer bound to the reporting machine."""

from yoke_core.api.machine_function_auth import machine_credential_refusal


MACHINE_ID = "11111111-1111-4111-8111-111111111111"


def _envelope(function: str, machine_id: str | None = MACHINE_ID):
    payload = {} if machine_id is None else {"machine_id": machine_id}
    return {"function": function, "payload": payload}


def test_relay_call_refuses_an_unbound_legacy_credential():
    refusal = machine_credential_refusal(_envelope("session_control.relay.claim"), None)
    assert refusal is not None
    assert refusal[0] == "machine_credential_required"
    assert "installer" in refusal[1]


def test_relay_call_refuses_a_different_machine_identity():
    refusal = machine_credential_refusal(
        _envelope("session_control.relay.liveness"),
        "22222222-2222-4222-8222-222222222222",
    )
    assert refusal is not None
    assert refusal[0] == "machine_credential_mismatch"


def test_bound_relay_and_human_functions_continue():
    assert (
        machine_credential_refusal(_envelope("session_control.relay.claim"), MACHINE_ID)
        is None
    )
    assert machine_credential_refusal(_envelope("machine.list", None), None) is None


def test_bound_machine_credential_requires_every_relay_body_to_name_it():
    refusal = machine_credential_refusal(
        _envelope("session_control.relay.report", None), MACHINE_ID
    )

    assert refusal is not None
    assert refusal[0] == "machine_credential_mismatch"
