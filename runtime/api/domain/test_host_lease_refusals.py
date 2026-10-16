"""Host refusal messages identify actual custody and the route to admission."""

from types import SimpleNamespace

import pytest

from yoke_core.domain import machine_qa_execution_protocol as protocol


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("missing", "no lease was issued"),
        ("unbound", "does not name a machine"),
        ("target", "different target"),
        ("session", "another session owns it"),
        ("actor", "another actor owns it"),
        ("expired", "no longer active"),
    ],
)
def test_lease_refusal_explains_actual_state_and_admission(
    monkeypatch, scenario, expected
):
    lease = SimpleNamespace(
        id=7,
        target=SimpleNamespace(machine_id="linux-lab"),
        is_active=True,
        key=protocol.host_claim_key("linux-lab"),
        session_id="owner",
        actor_id="1",
    )
    if scenario == "unbound":
        lease.target.machine_id = None
    elif scenario == "target":
        lease.key = "different"
    elif scenario == "session":
        lease.session_id = "other"
    elif scenario == "actor":
        lease.actor_id = "2"
    elif scenario == "expired":
        lease.is_active = False

    def lock(*_):
        if scenario == "missing":
            raise protocol.CoordinationClaimNotFoundError("missing")
        return lease

    monkeypatch.setattr(protocol, "_lock_submission_claim", lock)
    monkeypatch.setattr(
        protocol,
        "load_test_machine_contract",
        lambda *_, **__: SimpleNamespace(settings={"resource_name": "linux-lab"}),
    )
    with pytest.raises(protocol.MachineQaProtocolError) as error:
        protocol._validate_lease_owner(
            None,
            project="yoke",
            session_id="owner",
            actor_id="1",
            lease_id=7,
            allow_released=False,
        )
    text = str(error.value)
    assert expected in text
    assert "Declare method_config.machine" in text
    assert "scoped plan" in text
    if scenario not in {"missing", "unbound"}:
        assert "linux-lab" in text
        assert f"session {lease.session_id}" in text
        assert f"actor {lease.actor_id}" in text


def test_released_receipt_can_still_be_validated_for_idempotent_submission(monkeypatch):
    lease = SimpleNamespace(
        id=7,
        target=SimpleNamespace(machine_id="linux-lab"),
        is_active=False,
        key="released",
        session_id="owner",
        actor_id="1",
    )
    monkeypatch.setattr(protocol, "_lock_submission_claim", lambda *_: lease)
    machine = SimpleNamespace(settings={"resource_name": "linux-lab"})
    monkeypatch.setattr(
        protocol, "load_test_machine_contract", lambda *_, **__: machine
    )
    assert protocol._validate_lease_owner(
        None,
        project="yoke",
        session_id="owner",
        actor_id="1",
        lease_id=7,
        allow_released=True,
    ) == (lease, machine)


def test_busy_host_names_actual_holder_and_wait_step():
    lease = SimpleNamespace(id=7, session_id="owner", actor_id="1")
    text = str(protocol.MachineQaProtocolLeaseHeld(lease=lease, machine="linux-lab"))
    assert "linux-lab" in text
    assert "session owner and actor 1" in text
    assert "Wait for that execution to finish" in text


def test_released_receipt_refusal_does_not_advise_repeating_host_action():
    from yoke_core.domain.machine_qa_lease_messages import released_without_receipt

    lease = SimpleNamespace(
        id=7, session_id="owner", target=SimpleNamespace(machine_id="linux-lab")
    )
    text = released_without_receipt(lease)
    assert "linux-lab" in text
    assert "session owner" in text
    assert "recover its receipt" in text
    assert "do not repeat the host action" in text
