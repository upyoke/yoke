"""Repair stale local references while preserving machine connection selection."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from yoke_contracts.machine_config.runtime import write_config

from yoke_cli.commands import local_universe as commands
from yoke_cli.config import local_universe_setup as setup, writer, machine_config
from runtime.api.cli.local_universe_cli_test_support import (
    _stub_engine,
    _config,
    machine_home as machine_home,
)


def prod_active():
    writer.set_connection(
        "prod", transport="https", api_url="https://api.example", token="t" * 40
    )
    writer.set_active_env("prod")


@pytest.mark.parametrize("activate", [False, True])
def test_missing_secret_repairs_without_force_and_activation_is_explicit(
    monkeypatch, machine_home, capsys, activate
):
    monkeypatch.setattr(setup, "_engine", _stub_engine)
    setup.run_local_init()
    prod_active()
    secret = Path(
        _config(machine_home)["connections"]["local"]["credential_source"]["path"]
    )
    secret.unlink()
    assert setup.inspect_local_state()["state"] == setup.LOCAL_UNIVERSE_VERIFY
    args = ["--local", "--json"] + (["--activate"] if activate else [])
    assert commands.init(args) == 0
    output = capsys.readouterr()
    assert "repaired connections.local: missing credential file" in output.err
    assert secret.is_file()
    assert json.loads(output.out)["active_env"] == ("local" if activate else "prod")


def test_force_rewrite_preserves_active_prod(monkeypatch, machine_home):
    monkeypatch.setattr(setup, "_engine", _stub_engine)
    setup.run_local_init()
    prod_active()
    monkeypatch.setattr(
        setup,
        "_engine",
        lambda: _stub_engine(dsn="host=/elsewhere user=yoke dbname=yoke"),
    )
    report = setup.run_local_init(force=True)
    assert report["connection"]["written"]
    assert report["active_env"] == "prod"


@pytest.mark.parametrize("missing_secret", [True, False])
def test_prod_marked_local_connection_still_requires_force(
    monkeypatch, machine_home, missing_secret
):
    writer.set_connection(
        "local",
        transport="local-postgres",
        dsn="host=/sock user=yoke dbname=yoke",
        protected=True,
    )
    if missing_secret:
        Path(
            _config(machine_home)["connections"]["local"]["credential_source"]["path"]
        ).unlink()
    monkeypatch.setattr(setup, "_engine", _stub_engine)
    with pytest.raises(setup.LocalUniverseSetupError, match="--force"):
        setup.run_local_init()


@pytest.mark.parametrize("stale_universe", [True, False])
def test_stale_actor_is_rerecorded_against_the_owned_cluster(
    monkeypatch, machine_home, test_db, stale_universe
):
    from yoke_core.domain import db_backend, local_universe_operating_actor as binding
    from yoke_core.domain.org_schema import seed_default_org
    from yoke_core.domain.universe_identity import universe_fingerprint

    payload = machine_config.load_config()
    payload["schema_version"] = 1
    write_config(machine_config.config_path(), payload)
    seed_default_org(test_db)
    actor_id = int(
        test_db.execute(
            "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    )
    test_db.commit()
    # Keep real binding persistence and resolution; use this test's real database.
    dsn = db_backend.resolve_pg_dsn()
    writer.set_connection(
        "local",
        transport="local-postgres",
        dsn=dsn if not stale_universe else "host=/old-cluster dbname=yoke",
    )
    payload = machine_config.load_config()
    payload["connections"]["local"]["operating_actor"] = {
        "actor_id": actor_id if stale_universe else 999999,
        "universe": "foreign@2020" if stale_universe else universe_fingerprint(test_db),
    }
    write_config(machine_config.config_path(), payload)
    monkeypatch.setattr(
        setup,
        "_engine",
        lambda: SimpleNamespace(
            unsupported_host_reason=lambda: "",
            birth=lambda **kw: {"dsn": dsn, "human_actor_id": actor_id},
        ),
    )
    monkeypatch.setattr(
        setup,
        "_record_operating_actor",
        lambda report, path: binding.record_operating_actor(
            report["human_actor_id"], dsn=report["dsn"], env="local", config_path=path
        ),
    )
    prod_active()
    lines = []
    report = setup.run_local_init(emit=lines.append)
    assert report["operating_actor_repaired"]
    assert report["active_env"] == "prod"
    assert not binding.inspect_operating_actor(dsn=dsn)
    assert _config(machine_home)["connections"]["local"]["operating_actor"] == {
        "actor_id": actor_id,
        "universe": universe_fingerprint(test_db),
    }
    assert any("repaired" in line and "operating actor" in line for line in lines)
