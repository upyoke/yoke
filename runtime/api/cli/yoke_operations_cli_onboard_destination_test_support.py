# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from types import SimpleNamespace

import pytest

from yoke_cli import main as yoke_operations_cli

from yoke_cli.config import local_universe_setup

from yoke_cli.config import onboard_apply_resume

from yoke_cli.config import onboard_apply_snapshot

from yoke_cli.config import onboard_destinations

from yoke_cli.config import writer

FAKE_DSN = "postgresql://yoke@/yoke?host=/fake/local-universe/sock"

LOCAL = local_universe_setup.LOCAL_ENV


class _FakeEngine:
    """Stands in for the embedded-Postgres engine behind the birth seam."""

    def unsupported_host_reason(self):
        return ""

    def birth(self, *, org_name=None, admin_name=None, emit=lambda _line: None):
        emit("fake engine: universe ready")
        return {
            "dsn": FAKE_DSN,
            "born": True,
            "human_actor_id": 1,
            "cluster": {"root": "/fake/local-universe", "running": True},
            "org": {"name": org_name or "Local Org", "slug": "local-org"},
        }


@pytest.fixture()
def fake_engine(monkeypatch):
    monkeypatch.setattr(local_universe_setup, "_engine", lambda: _FakeEngine())
    monkeypatch.setattr(
        local_universe_setup, "_record_operating_actor", lambda report, path: None
    )


@pytest.fixture()
def scratch_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.delenv(onboard_destinations.DESTINATION_OVERRIDE, raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)
    return home


def _config_payload(home: Path) -> dict:
    return json.loads((home / "config.json").read_text(encoding="utf-8"))


def _normalized_local_connection(home: Path) -> dict:
    payload = _config_payload(home)
    connection = dict(payload["connections"][LOCAL])
    source = dict(connection.get("credential_source") or {})
    dsn_path = source.pop("path", "")
    connection["credential_source"] = source
    connection["dsn_value"] = Path(dsn_path).read_text(encoding="utf-8").strip()
    connection["active_env"] = payload.get("active_env")
    return connection
