"""`yoke relay status` includes local report-delivery health."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import session_control_relay as relay
from yoke_cli.commands.adapters import session_control_relay_report as report_cli
from yoke_harness import session_relay
from yoke_harness.session_relay_health import (
    record_relay_run_refusal,
    record_report_failure,
)
from yoke_harness.session_relay_poll_health import (
    record_poll_failure,
    record_poll_success,
    reset_poll_outcome,
)
from yoke_harness.session_relay_report_delivery import deliver_terminal_report


@pytest.fixture(autouse=True)
def _current_release(monkeypatch) -> None:
    monkeypatch.setattr(
        relay,
        "release_status_payload",
        lambda _status, *, refresh_served: {
            "release_current": True,
            "release_error_code": None,
        },
    )


def test_degraded_report_delivery_is_named_and_exits_nonzero(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    record_report_failure(tmp_path, error_code="transport_error")
    monkeypatch.setattr(
        relay,
        "_plist_operation",
        lambda _action: SimpleNamespace(
            supported=True,
            environment="prod",
            label="com.upyoke.relay",
            plist_present=True,
            plist_current=True,
            loaded=True,
            plist_path=tmp_path / "relay.plist",
            state_dir=tmp_path,
        ),
    )

    assert relay.relay_status(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["relay_health"]["state"] == "retrying"
    assert payload["relay_health"]["report_failure"]["error_code"] == (
        "transport_error"
    )
    assert "leave the relay running" in payload["relay_health_recovery"]


def test_build_refusal_status_names_revisions_and_deploy(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    record_relay_run_refusal(
        tmp_path,
        pinned_release="0.1.1+launch.365",
        local_revision="aaaaaaaaaaaa",
        server_revision="v0.1.1+launch.365",
        ahead_by=30,
    )
    monkeypatch.setattr(
        relay,
        "_plist_operation",
        lambda _action: SimpleNamespace(
            supported=True,
            environment="prod",
            label="com.upyoke.relay",
            plist_present=True,
            plist_current=True,
            loaded=True,
            plist_path=tmp_path / "relay.plist",
            state_dir=tmp_path,
        ),
    )

    assert relay.relay_status(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["relay_health"]["state"] == "refused"
    assert "aaaaaaaaaaaa" in payload["relay_health_recovery"]
    assert "v0.1.1+launch.365" in payload["relay_health_recovery"]
    assert "recovery: deploy" in payload["relay_health_recovery"]


def _terminal_payload() -> dict[str, object]:
    return {
        "relay_id": "machine:11111111-1111-4111-8111-111111111111",
        "machine_id": "11111111-1111-4111-8111-111111111111",
        "job_kind": "launch",
        "job_id": "11111111-1111-4111-8111-111111111111",
        "lease_id": "22222222-2222-4222-8222-222222222222",
        "result": "outcome_unknown",
        "evidence": {"result_code": "native_exit"},
    }


def test_report_quarantine_command_requires_and_preserves_permanent_rejection(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    deliver_terminal_report(
        lambda **_kwargs: SimpleNamespace(
            success=False,
            error=SimpleNamespace(code="report_conflict"),
        ),
        session_relay.RELAY_REPORT_FUNCTION_ID,
        _terminal_payload(),
        state_dir=tmp_path,
        timeout_s=10,
    )
    pending = next((tmp_path / "pending-reports").glob("*.json"))
    monkeypatch.setattr(report_cli, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(report_cli, "_relay_state_dir", lambda: tmp_path)

    assert report_cli.relay_report_quarantine([pending.stem, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["report_id"] == pending.stem
    assert payload["report"]["error_code"] == "report_conflict"
    assert payload["report"]["payload_sha256"]
    assert "do not replay" in payload["recovery"]
    assert not pending.exists()


def test_report_quarantine_command_leaves_transport_failure_retryable(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    deliver_terminal_report(
        lambda **_kwargs: (_ for _ in ()).throw(OSError("offline")),
        session_relay.RELAY_REPORT_FUNCTION_ID,
        _terminal_payload(),
        state_dir=tmp_path,
        timeout_s=10,
    )
    pending = next((tmp_path / "pending-reports").glob("*.json"))
    monkeypatch.setattr(report_cli, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(report_cli, "_relay_state_dir", lambda: tmp_path)

    assert report_cli.relay_report_quarantine([pending.stem, "--json"]) == 1
    failure = json.loads(capsys.readouterr().err)
    assert failure["code"] == "relay_report_quarantine_not_allowed"
    assert "must retry" in failure["recovery"]
    assert pending.exists()


def test_quarantined_status_teaches_terminal_recovery_without_replay(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    deliver_terminal_report(
        lambda **_kwargs: SimpleNamespace(
            success=False,
            error=SimpleNamespace(code="report_conflict"),
        ),
        session_relay.RELAY_REPORT_FUNCTION_ID,
        _terminal_payload(),
        state_dir=tmp_path,
        timeout_s=10,
    )
    pending = next((tmp_path / "pending-reports").glob("*.json"))
    monkeypatch.setattr(report_cli, "is_subagent_execution", lambda: False)
    monkeypatch.setattr(report_cli, "_relay_state_dir", lambda: tmp_path)
    assert report_cli.relay_report_quarantine([pending.stem, "--json"]) == 0
    capsys.readouterr()
    monkeypatch.setattr(
        relay,
        "_plist_operation",
        lambda _action: SimpleNamespace(
            supported=True,
            environment="prod",
            label="com.upyoke.relay",
            plist_present=True,
            plist_current=True,
            loaded=True,
            plist_path=tmp_path / "relay.plist",
            state_dir=tmp_path,
        ),
    )

    assert relay.relay_status(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert "report_conflict" in payload["relay_health_recovery"]
    assert "do not replay" in payload["relay_health_recovery"]
    assert "yoke relay report quarantine" in payload["relay_health_recovery"]


def _loaded(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        relay,
        "_plist_operation",
        lambda _action: SimpleNamespace(
            supported=True,
            environment="prod",
            label="com.upyoke.relay",
            plist_present=True,
            plist_current=True,
            loaded=True,
            plist_path=tmp_path / "relay.plist",
            state_dir=tmp_path,
        ),
    )


def test_failed_poll_is_named_even_when_report_delivery_is_healthy(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    record_poll_failure(tmp_path, error_code="machine_credential_required")
    _loaded(monkeypatch, tmp_path)

    assert relay.relay_status(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    poll = payload["relay_health"]["poll_outcome"]
    assert payload["relay_health"]["state"] == "healthy"
    assert poll["status"] == "failed"
    assert poll["error_code"] == "machine_credential_required"
    assert poll["consecutive_failures"] == 1
    recovery = payload["relay_health_recovery"]
    assert "Control-plane connection failed" in recovery
    assert "yoke connect" in recovery
    assert "alone does not mint credentials" in recovery


def test_poll_recovery_clears_current_failure_and_status_is_healthy(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    record_poll_failure(tmp_path, error_code="machine_credential_required")
    record_poll_failure(tmp_path, error_code="machine_credential_required")
    record_poll_success(tmp_path)
    _loaded(monkeypatch, tmp_path)

    assert relay.relay_status(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    poll = payload["relay_health"]["poll_outcome"]
    assert poll["status"] == "ok"
    assert "error_code" not in poll
    assert "consecutive_failures" not in poll
    assert poll["last_failed_at"]
    assert "connection failed" not in payload["relay_health_recovery"]


def test_restarted_daemon_does_not_inherit_a_healthy_poll_verdict(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    record_poll_success(tmp_path)
    reset_poll_outcome(tmp_path)
    _loaded(monkeypatch, tmp_path)

    assert relay.relay_status(["--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    poll = payload["relay_health"]["poll_outcome"]
    assert poll["status"] == "pending"
    assert poll["last_succeeded_at"]
    assert "not completed a control-plane poll" in payload["relay_health_recovery"]
