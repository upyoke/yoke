"""Doctor coverage for one aggregate machine-relay health check."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config.session_relay_instance import RelayInstanceError
from yoke_core.engines import doctor_hc_session_relay as relay_hc
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.tools.session_relay_plist import RelayLaunchdStatus
from runtime.api.domain.session_launch_test_support import add_relay, launch_connection


def _status(
    tmp_path: Path,
    *,
    loaded: bool = True,
    follows_served_release: bool = True,
) -> RelayLaunchdStatus:
    return RelayLaunchdStatus(
        supported=True,
        plist_present=True,
        plist_current=True,
        loaded=loaded,
        plist_path=tmp_path / "com.upyoke.relay.plist",
        follows_served_release=follows_served_release,
    )


def _bind_instance(
    monkeypatch,
    tmp_path: Path,
    *,
    follows_served_release: bool = True,
    loaded: bool = True,
) -> None:
    """Bind the check to one resolved relay instance and its launchd status."""
    monkeypatch.setattr(relay_hc.sys, "platform", "darwin")
    monkeypatch.setattr(
        relay_hc,
        "resolve_relay_instance",
        lambda: SimpleNamespace(
            environment="local" if not follows_served_release else "prod",
            follows_served_release=follows_served_release,
        ),
    )
    monkeypatch.setattr(
        relay_hc,
        "relay_launchd_status",
        lambda **_kwargs: _status(
            tmp_path,
            loaded=loaded,
            follows_served_release=follows_served_release,
        ),
    )


def test_doctor_passes_only_when_plist_heartbeat_and_token_are_healthy(
    monkeypatch,
    tmp_path: Path,
) -> None:
    conn = launch_connection()
    add_relay(conn, connected_until="2099-01-01T00:00:00Z")
    _bind_instance(monkeypatch, tmp_path)
    monkeypatch.setattr(relay_hc, "_machine_id", lambda: "machine-1")
    monkeypatch.setattr(
        relay_hc, "_missing_credential_reference", lambda **_kwargs: ""
    )
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

    _bind_instance(monkeypatch, tmp_path)
    monkeypatch.setattr(relay_hc, "_machine_id", lambda: "machine-1")
    monkeypatch.setattr(
        relay_hc, "_missing_credential_reference", lambda **_kwargs: ""
    )
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
    _bind_instance(monkeypatch, tmp_path, loaded=False)
    monkeypatch.setattr(relay_hc, "_machine_id", lambda: "missing-machine")
    monkeypatch.setattr(
        relay_hc,
        "_missing_credential_reference",
        lambda **_kwargs: "active connection has no owner-only API token reference",
    )
    rec = RecordCollector()

    relay_hc.hc_session_relay(conn, DoctorArgs(), rec)

    assert rec.results[0].result == "FAIL"
    assert "not loaded" in rec.results[0].detail
    assert "no currently connected relay heartbeat" in rec.results[0].detail
    assert "API token reference" in rec.results[0].detail


def test_doctor_asks_a_local_relay_for_its_dsn_not_an_api_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A local install authorizes by DSN, so demanding a token would fail it."""
    conn = launch_connection()
    add_relay(conn, connected_until="2099-01-01T00:00:00Z")
    _bind_instance(monkeypatch, tmp_path, follows_served_release=False)
    monkeypatch.setattr(relay_hc, "_machine_id", lambda: "machine-1")
    asked: list[bool] = []

    def credential(*, follows_served_release: bool) -> str:
        asked.append(follows_served_release)
        return ""

    monkeypatch.setattr(relay_hc, "_missing_credential_reference", credential)
    rec = RecordCollector()

    relay_hc.hc_session_relay(conn, DoctorArgs(), rec)

    assert asked == [False]
    assert rec.results[0].result == "PASS"


def test_doctor_reports_a_connection_that_owns_no_relay_as_not_applicable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A refusal is a diagnosis, not a crash, and never a silent pass."""
    monkeypatch.setattr(relay_hc.sys, "platform", "darwin")

    def refuse():
        raise RelayInstanceError("machine relay refuses a prod local-postgres connection")

    monkeypatch.setattr(relay_hc, "resolve_relay_instance", refuse)
    rec = RecordCollector()

    relay_hc.hc_session_relay(None, DoctorArgs(), rec)

    assert rec.results[0].result == relay_hc.NOT_APPLICABLE
    assert "prod local-postgres" in rec.results[0].detail


@pytest.mark.parametrize(
    ("follows_served_release", "expected"),
    ((True, "API token reference"), (False, "DSN reference")),
)
def test_missing_credential_names_the_reference_each_plane_needs(
    monkeypatch, follows_served_release: bool, expected: str
) -> None:
    monkeypatch.setattr(
        relay_hc.machine_config,
        "active_connection",
        lambda: {"credential_source": {"kind": "env"}},
    )

    detail = relay_hc._missing_credential_reference(
        follows_served_release=follows_served_release,
    )

    assert expected in detail
