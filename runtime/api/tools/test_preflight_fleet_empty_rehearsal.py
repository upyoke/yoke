"""An empty fleet rehearsal proves nothing, so it never records coverage."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.api.tools.migration_admin_selected_readiness_test_support import (
    _authority,
    _declare_admin,
)
from yoke_core.domain import connected_env_readiness as readiness
from yoke_core.domain import local_universe, local_universe_autostart
from yoke_core.domain import migration_fleet_preflight
from yoke_core.tools import fleet_rehearsal_receipt_write as receipt_write
from yoke_core.tools import migration_fleet_selection
from yoke_core.tools import preflight_fleet_migrations as preflight


@pytest.mark.parametrize("record", [True, False])
def test_empty_fleet_records_no_receipt(monkeypatch, tmp_path, capsys, record):
    recorded: list[dict] = []
    monkeypatch.setenv("YOKE_ENV", "release")
    _declare_admin(monkeypatch, {"stage": "stage-db-admin"})
    empty = migration_fleet_selection.FleetTarget(
        project="yoke",
        model_name="primary",
        plan=SimpleNamespace(history=("0001_existing",)),
        databases=lambda _dsn_for: [],
        schema_shape_digest=lambda: "digest-for-test",
    )
    monkeypatch.setattr(
        migration_fleet_selection, "resolve", lambda *_a, **_k: (empty, "")
    )
    monkeypatch.setattr(receipt_write, "receipt_plane_refusal", lambda **_kw: "")
    monkeypatch.setattr(
        receipt_write,
        "record_receipt",
        lambda **kwargs: (recorded.append(kwargs), ("run", ""))[1],
    )
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
    monkeypatch.setattr(
        migration_fleet_preflight, "rehearse_fleet", lambda _dsn_for, **_kw: []
    )
    args = ["--project", "yoke", "stage"]
    if record:
        args += ["--record-receipt", "--product-sha", "abc"]

    assert preflight.main(args) == (1 if record else 0)
    assert recorded == []
    err = capsys.readouterr().err
    assert "no database was rehearsed" in err
    assert "no receipt was recorded" in err
