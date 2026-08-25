"""Doctor coverage for one aggregate machine-relay health check."""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines import doctor_hc_session_relay as relay_hc
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.tools.session_relay_plist import RelayLaunchdStatus
from runtime.api.domain.session_launch_test_support import add_relay, launch_connection


def _status(tmp_path: Path, *, loaded: bool = True) -> RelayLaunchdStatus:
    return RelayLaunchdStatus(
        supported=True,
        plist_present=True,
        plist_current=True,
        loaded=loaded,
        plist_path=tmp_path / "com.upyoke.relay.plist",
    )


def test_doctor_passes_only_when_plist_heartbeat_and_token_are_healthy(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = launch_connection()
    add_relay(conn, connected_until="2099-01-01T00:00:00Z")
    monkeypatch.setattr(relay_hc.sys, "platform", "darwin")
    monkeypatch.setattr(relay_hc, "relay_launchd_status", lambda: _status(tmp_path))
    monkeypatch.setattr(relay_hc, "_machine_id", lambda: "machine-1")
    monkeypatch.setattr(relay_hc, "_token_reference_active", lambda: True)
    rec = RecordCollector()

    relay_hc.hc_session_relay(conn, DoctorArgs(), rec)

    assert rec.results[0].result == "PASS"
    assert "relay-1" in rec.results[0].detail


def test_doctor_reads_remote_heartbeat_without_a_local_database(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []

    def list_relays(function, payload):
        calls.append((function, payload))
        return {
            "relays": [{
                "relay_id": "relay-remote",
                "machine_id": "machine-1",
                "last_seen_at": "2026-08-25T12:00:00Z",
                "liveness": "connected",
            }],
        }

    monkeypatch.setattr(relay_hc.sys, "platform", "darwin")
    monkeypatch.setattr(relay_hc, "relay_launchd_status", lambda: _status(tmp_path))
    monkeypatch.setattr(relay_hc, "_machine_id", lambda: "machine-1")
    monkeypatch.setattr(relay_hc, "_token_reference_active", lambda: True)
    monkeypatch.setattr(relay_hc, "relay", list_relays)
    rec = RecordCollector()

    relay_hc.hc_session_relay(None, DoctorArgs(), rec)

    assert rec.results[0].result == "PASS"
    assert "relay-remote" in rec.results[0].detail
    assert calls == [(
        relay_hc._RELAY_LIST_FUNCTION_ID,
        {"state": "active", "limit": 500},
    )]


def test_doctor_combines_missing_loaded_heartbeat_and_token_findings(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = launch_connection()
    monkeypatch.setattr(relay_hc.sys, "platform", "darwin")
    monkeypatch.setattr(
        relay_hc,
        "relay_launchd_status",
        lambda: _status(tmp_path, loaded=False),
    )
    monkeypatch.setattr(relay_hc, "_machine_id", lambda: "missing-machine")
    monkeypatch.setattr(relay_hc, "_token_reference_active", lambda: False)
    rec = RecordCollector()

    relay_hc.hc_session_relay(conn, DoctorArgs(), rec)

    assert rec.results[0].result == "FAIL"
    assert "not loaded" in rec.results[0].detail
    assert "no currently connected relay heartbeat" in rec.results[0].detail
    assert "API token reference" in rec.results[0].detail
