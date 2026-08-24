"""CLI contracts for exact peer-wake relay reservations."""

from dataclasses import dataclass

from yoke_cli.commands.adapters import session_control_relay as relay


@dataclass(frozen=True)
class _Outcome:
    state: str
    next_poll_seconds: int


def test_broker_flags_force_the_exact_reserved_work_path(monkeypatch, capsys) -> None:
    lease_id = "22222222-2222-4222-8222-222222222222"
    seen = []
    monkeypatch.setattr(relay, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(
        relay,
        "_serve_once",
        lambda **kwargs: seen.append(kwargs) or _Outcome("active", 60),
    )
    valid = ["--broker", "--broker-lease", lease_id, "--json"]
    assert relay.relay_serve_once(valid) == 0
    assert relay.relay_serve_once(["--broker", "--json"]) == 2
    assert relay.relay_serve_once(["--broker-lease", lease_id]) == 2
    assert relay.relay_serve_once(
        ["--broker", "--broker-lease", "not-a-uuid"]
    ) == 2
    monkeypatch.setattr(relay, "is_subagent_execution", lambda: True)
    assert relay.relay_serve_once(["--json"]) == 2
    assert seen == [{"broker_only": True, "broker_lease_id": lease_id}]
    assert "registered top-level session" in capsys.readouterr().err
