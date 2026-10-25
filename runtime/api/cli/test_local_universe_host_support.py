"""Setup shows local mode as unavailable on a host the embedded engine refuses.

The engine's own host check (``postgres_binaries.require_supported_host``)
feeds the local-universe state, so the first local setup screen states the
host reason instead of letting every later question run before Apply refuses.
"""

from __future__ import annotations

import pytest

from yoke_cli.config import local_universe_setup as setup
from yoke_cli.config.onboard_wizard_local_universe_summary import (
    local_universe_summary_lines,
    local_universe_summary_rows,
)
from yoke_contracts.machine_config import schema as contract
from yoke_core.domain import postgres_binaries as pb


def _mac(monkeypatch, version: str) -> None:
    monkeypatch.setattr(pb.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(pb.platform, "mac_ver", lambda: (version, ("", "", ""), ""))


@pytest.fixture
def config_path(tmp_path):
    return str(tmp_path / "config.yaml")


def test_old_macos_reports_local_mode_unavailable_with_host_reason(
    monkeypatch, config_path
):
    _mac(monkeypatch, "12.7.6")

    state = setup.inspect_local_state(config_path)

    assert state["state"] == setup.LOCAL_UNIVERSE_UNAVAILABLE
    assert state["host_unsupported"] is True
    assert state["reason"].startswith("embedded_postgres_macos_unsupported:")
    assert "detected macOS 12.7.6" in state["reason"]


def test_host_reason_wins_over_a_saved_local_connection(monkeypatch, config_path):
    saved = {
        "active_env": setup.LOCAL_ENV,
        "connections": {
            setup.LOCAL_ENV: {
                "transport": contract.DEFAULT_TRANSPORT,
                "dsn": "postgresql://localhost/yoke",
            }
        },
    }
    monkeypatch.setattr(setup.machine_config, "load_config", lambda _path: saved)
    monkeypatch.setattr(setup, "stored_dsn", lambda entry: entry["dsn"])
    _mac(monkeypatch, "26.0")
    assert setup.inspect_local_state(config_path)["state"] == setup.LOCAL_UNIVERSE_VERIFY
    _mac(monkeypatch, "15.4")

    state = setup.inspect_local_state(config_path)

    assert state["state"] == setup.LOCAL_UNIVERSE_UNAVAILABLE
    assert state["host_unsupported"] is True
    assert "detected macOS 15.4" in state["reason"]


def test_unreadable_macos_version_is_unavailable(monkeypatch, config_path):
    _mac(monkeypatch, "")

    state = setup.inspect_local_state(config_path)

    assert state["state"] == setup.LOCAL_UNIVERSE_UNAVAILABLE
    assert state["reason"].startswith("embedded_postgres_macos_version_unknown:")


def test_supported_macos_offers_a_new_universe(monkeypatch, config_path):
    _mac(monkeypatch, "26.0")

    state = setup.inspect_local_state(config_path)

    assert state["state"] == setup.LOCAL_UNIVERSE_CREATE
    assert "host_unsupported" not in state


def test_summary_states_the_host_reason_and_only_offers_back(monkeypatch, config_path):
    _mac(monkeypatch, "12.7.6")
    state = setup.inspect_local_state(config_path)

    lines = local_universe_summary_lines(state)

    assert lines[0] == "This machine cannot run local mode."
    assert lines[1] == state["reason"]
    assert "A team server or upyoke.com" in lines[2]
    assert not any("connection record" in line for line in lines)
    assert [row.value for row in local_universe_summary_rows(state)] == ["back"]


def test_host_recovery_names_only_remote_alternatives(monkeypatch, config_path):
    _mac(monkeypatch, "12.7.6")

    reason = setup.inspect_local_state(config_path)["reason"]

    assert "team server or upyoke.com" in reason
    assert "Docker" not in reason
