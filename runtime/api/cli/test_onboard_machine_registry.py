"""Onboarding Apply puts this machine in the registry, or says why it could not."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import onboard
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_machine_registry
from yoke_cli.config import onboard_session_relay
from yoke_cli.config import machine_registration


def _apply(tmp_path: Path, monkeypatch, outcome: dict) -> dict:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        onboard_session_relay,
        "install",
        lambda **_kwargs: onboard_session_relay.RelayInstallOutcome(
            installed=True, reused=False
        ),
    )
    calls: list[object] = []

    def register(config_path=None):
        calls.append(config_path)
        return outcome

    monkeypatch.setattr(onboard_machine_registry, "register_this_machine", register)
    report = onboard.build_report(
        config_path=tmp_path / "home" / "config.json",
        env_name="prod",
        api_url="https://api.example.test",
        destination=onboard_destinations.DESTINATION_SERVER,
        token="actor-token",
        token_source_kind="argument",
        mode="quick",
        apply=True,
        check_identity=False,
    )
    report["_register_calls"] = calls
    return report


def test_apply_registers_this_machine_once(tmp_path: Path, monkeypatch) -> None:
    report = _apply(
        tmp_path,
        monkeypatch,
        {"machine_id": "machine-1", "registered": True, "name": "test-mac"},
    )

    assert report["applied"] is True
    assert len(report["_register_calls"]) == 1
    assert report["machine_registry"]["registered"] is True
    assert onboard_machine_registry.summary_lines(report["machine_registry"]) == ()


def test_apply_reports_a_registry_refusal_without_failing(
    tmp_path: Path, monkeypatch
) -> None:
    report = _apply(
        tmp_path,
        monkeypatch,
        {
            "machine_id": "machine-1",
            "registered": False,
            "reason": "machine_owner_mismatch: registered to another actor",
        },
    )

    assert report["applied"] is True
    rendered = onboard.render_human(report)
    assert "machine_owner_mismatch: registered to another actor" in rendered
    assert "yoke machine register" in rendered


def test_review_plans_the_registration_in_the_core_database() -> None:
    from yoke_cli.config.onboard_wizard_plan_review import classify_plan

    grouped = classify_plan({"plan": {"steps": onboard_machine_registry.plan_steps()}})

    assert grouped["core"] == ["Register this machine in the machine registry"]


def test_setup_complete_names_the_refusal_and_its_recovery() -> None:
    from yoke_cli.config.onboard_wizard_apply_steps import (
        apply_success_body_from_report,
    )

    widgets = apply_success_body_from_report(
        None,
        {"machine_registry": {"registered": False, "reason": "the plane refused"}},
    )

    rendered = "\n".join(str(widget.render()) for widget in widgets)
    assert "the plane refused" in rendered
    assert "yoke machine register" in rendered


def test_https_registration_persists_only_the_returned_machine_bearer(
    monkeypatch,
) -> None:
    from yoke_cli.config import machine_config, writer
    from yoke_contracts.machine_config import schema as contract

    stored = []
    monkeypatch.setattr(
        machine_config,
        "active_connection",
        lambda _path=None: {"transport": contract.TRANSPORT_HTTPS},
    )
    monkeypatch.setattr(machine_config, "active_env", lambda _path=None: "prod")
    monkeypatch.setattr(
        writer,
        "set_credential",
        lambda env, *, token, path=None: stored.append((env, token, path)),
    )

    failure = machine_registration._persist_credential(
        {"credential": {"token": "machine-secret"}}, "/tmp/config.json"
    )

    assert failure is None
    assert stored == [("prod", "machine-secret", "/tmp/config.json")]


def test_https_registration_refuses_a_success_without_a_bearer(monkeypatch) -> None:
    from yoke_cli.config import machine_config
    from yoke_contracts.machine_config import schema as contract

    monkeypatch.setattr(
        machine_config,
        "active_connection",
        lambda _path=None: {"transport": contract.TRANSPORT_HTTPS},
    )

    failure = machine_registration._persist_credential({}, None)

    assert failure and failure.startswith("machine_credential_unsupported:")
