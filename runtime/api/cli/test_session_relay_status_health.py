"""`yoke relay status` includes local report-delivery health."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import session_control_relay as relay
from yoke_harness.session_relay_health import (
    record_relay_run_refusal,
    record_report_failure,
)


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
