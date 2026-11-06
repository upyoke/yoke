"""Fleet copies retain the explicitly selected admin forward for their lifetime."""

import os
from types import SimpleNamespace

import pytest

from runtime.api.tools.migration_admin_selected_readiness_test_support import (
    _authority,
    _declare_admin,
    _select_yoke_fleet,
)
from yoke_core.domain import connected_env_readiness as readiness
from yoke_core.domain import connected_env_readiness_connector as connector
from yoke_core.domain import connected_env_tunnel_coordination as coordination
from yoke_core.domain import local_universe, local_universe_autostart
from yoke_core.domain import migration_fleet_preflight
from yoke_core.tools import preflight_fleet_migrations as preflight


@pytest.mark.parametrize("outcome", ["pass", "fail", "raise"])
def test_fleet_holds_admin_lease_until_copy_finishes(monkeypatch, tmp_path, outcome):
    port = 6548
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    monkeypatch.setenv("YOKE_ENV", "unrelated")
    _declare_admin(monkeypatch, {"stage": "stage-db-admin"})
    _select_yoke_fleet(monkeypatch)
    monkeypatch.setattr(readiness, "activate_selected_postgres", _authority)
    monkeypatch.setattr(
        local_universe, "ensure_engine_binaries", lambda _emit: tmp_path
    )
    monkeypatch.setattr(
        local_universe,
        "cluster_spec",
        lambda **_kw: SimpleNamespace(sock_dir=tmp_path / "socket"),
    )
    monkeypatch.setattr(
        local_universe_autostart, "ensure_running", lambda *_a, **_k: None
    )

    def detect():
        assert os.environ["YOKE_ENV"] == "stage-db-admin"
        return connector.Detection(
            connector.CONNECTOR_LOCAL_SSH_TUNNEL_PG,
            "stage-db-admin",
            None,
            None,
            local_port=port,
        )

    def rehearse(_dsn_for, **kwargs):
        assert kwargs["source_environment"] == "stage-db-admin"
        assert os.environ["YOKE_ENV"] == "unrelated"
        leases = coordination.active_leases(port)
        assert len(leases) == 1
        assert "fleet migration rehearsal of stage" == leases[0].reason
        assert coordination.active_leases(6547) == []
        if outcome == "raise":
            raise RuntimeError("copy failed")
        return [SimpleNamespace(passed=outcome == "pass", line=outcome)]

    monkeypatch.setattr(coordination, "detect", detect)
    monkeypatch.setattr(migration_fleet_preflight, "rehearse_fleet", rehearse)
    args = ["--project", "yoke", "stage", "yoke_alpha"]
    if outcome == "raise":
        with pytest.raises(RuntimeError, match="copy failed"):
            preflight.main(args)
    else:
        assert preflight.main(args) == (0 if outcome == "pass" else 1)
    assert coordination.active_leases(port) == []
    assert os.environ["YOKE_ENV"] == "unrelated"
