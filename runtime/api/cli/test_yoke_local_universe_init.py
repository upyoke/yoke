"""Local-universe initialization, machine config, and idempotency."""

import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from yoke_cli.commands import local_universe as commands
from yoke_cli.config import local_universe_setup as setup
from runtime.api.cli.local_universe_cli_test_support import (
    _EngineError,
    _stub_engine,
    _config,
    machine_home as machine_home,
)


def test_local_init_records_births_actor_after_connection_write(
    monkeypatch, machine_home
):
    monkeypatch.setattr(setup, "_engine", _stub_engine)
    recorded = []

    def record(report, config_path):
        assert (
            _config(machine_home)["connections"]["local"]["transport"]
            == "local-postgres"
        )
        recorded.append(report["human_actor_id"])

    monkeypatch.setattr(setup, "_record_operating_actor", record)
    setup.run_local_init()
    assert recorded == [1]


def test_actor_binding_failure_refuses_local_init_with_recovery(monkeypatch):
    def record(*args, **kwargs):
        raise RuntimeError("identity unavailable")

    monkeypatch.setattr(
        setup.importlib,
        "import_module",
        lambda module: SimpleNamespace(record_operating_actor=record),
    )
    with pytest.raises(
        setup.LocalUniverseSetupError, match="local_actor_binding_failed.*retry"
    ):
        setup._record_operating_actor({"human_actor_id": 1, "dsn": "host=/sock"}, None)


def test_init_local_writes_connection_secret_and_active_env(
    monkeypatch,
    machine_home,
    capsys,
):
    monkeypatch.setattr(setup, "_engine", _stub_engine)

    assert commands.init(["--local", "--json"]) == 0

    config = _config(machine_home)
    entry = config["connections"]["local"]
    assert entry["transport"] == "local-postgres"
    assert entry["prod"] is False
    assert config["active_env"] == "local"
    source = entry["credential_source"]
    assert source["kind"] == "dsn_file"
    secret = Path(source["path"])
    assert secret == machine_home / "secrets" / "local.dsn"
    assert secret.read_text(encoding="utf-8").strip() == (
        "host=/sock user=yoke dbname=yoke"
    )
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["born"] is True
    assert report["connection"]["written"] is True


def test_init_secures_machine_home_before_nested_runtime_writes(
    monkeypatch,
    machine_home,
    capsys,
):
    machine_home.mkdir(mode=0o775)
    machine_home.chmod(0o775)

    def engine_after_nested_write():
        (machine_home / "postgres" / "17.10.0").mkdir(
            mode=0o700, parents=True, exist_ok=True
        )
        assert stat.S_IMODE(machine_home.stat().st_mode) == 0o700
        return _stub_engine()

    monkeypatch.setattr(setup, "_engine", engine_after_nested_write)

    assert commands.init(["--local", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert stat.S_IMODE(machine_home.stat().st_mode) == 0o700


def test_init_refuses_symlink_machine_home(monkeypatch, tmp_path, capsys):
    target = tmp_path / "actual-machine-home"
    target.mkdir()
    selected = tmp_path / "selected-machine-home"
    selected.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(selected))
    engine_called = False

    def forbidden_engine():
        nonlocal engine_called
        engine_called = True
        return _stub_engine()

    monkeypatch.setattr(setup, "_engine", forbidden_engine)

    assert commands.init(["--local", "--json"]) == 1
    assert "could not be secured" in capsys.readouterr().err
    assert engine_called is False


def test_init_second_run_reports_without_rewriting(monkeypatch, machine_home, capsys):
    monkeypatch.setattr(setup, "_engine", _stub_engine)
    assert commands.init(["--local", "--json"]) == 0
    capsys.readouterr()

    monkeypatch.setattr(setup, "_engine", lambda: _stub_engine(born=False))
    assert commands.init(["--local", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["born"] is False
    assert report["connection"]["written"] is False
    assert _config(machine_home)["active_env"] == "local"


def test_init_refuses_to_clobber_conflicting_local_connection(
    monkeypatch,
    machine_home,
    capsys,
):
    monkeypatch.setattr(setup, "_engine", _stub_engine)
    assert commands.init(["--local", "--json"]) == 0
    capsys.readouterr()

    monkeypatch.setattr(
        setup,
        "_engine",
        lambda: _stub_engine(dsn="host=/elsewhere user=yoke dbname=yoke"),
    )
    assert commands.init(["--local", "--json"]) == 1
    err = capsys.readouterr().err
    assert "--force" in err

    assert commands.init(["--local", "--force", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["connection"]["written"] is True
    secret = machine_home / "secrets" / "local.dsn"
    assert secret.read_text(encoding="utf-8").strip() == (
        "host=/elsewhere user=yoke dbname=yoke"
    )


def test_init_updates_same_cluster_socket_relocation_without_force(
    monkeypatch,
    machine_home,
    capsys,
):
    old_dsn = "host=/old-socket user=yoke dbname=yoke"
    new_dsn = "host=/tmp/yoke-pg-501-example user=yoke dbname=yoke"
    monkeypatch.setattr(setup, "_engine", lambda: _stub_engine(dsn=old_dsn))
    assert commands.init(["--local", "--json"]) == 0
    capsys.readouterr()

    monkeypatch.setattr(
        setup,
        "_engine",
        lambda: _stub_engine(
            born=False,
            dsn=new_dsn,
            socket_dsn_aliases=(old_dsn,),
        ),
    )
    assert commands.init(["--local", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["connection"]["written"] is True
    secret = machine_home / "secrets" / "local.dsn"
    assert secret.read_text(encoding="utf-8").strip() == new_dsn


def test_init_socket_relocation_does_not_clear_prod_marker_without_force(
    monkeypatch,
    machine_home,
    capsys,
):
    from yoke_cli.config import writer

    old_dsn = "host=/old-socket user=yoke dbname=yoke"
    new_dsn = "host=/tmp/yoke-pg-501-example user=yoke dbname=yoke"
    writer.set_connection(
        "local",
        transport="local-postgres",
        dsn=old_dsn,
        prod=True,
    )
    monkeypatch.setattr(
        setup,
        "_engine",
        lambda: _stub_engine(
            born=False,
            dsn=new_dsn,
            socket_dsn_aliases=(old_dsn,),
        ),
    )

    assert commands.init(["--local", "--json"]) == 1
    assert "--force" in capsys.readouterr().err
    secret = machine_home / "secrets" / "local.dsn"
    assert secret.read_text(encoding="utf-8").strip() == old_dsn

    assert commands.init(["--local", "--force", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["connection"]["written"] is True
    assert secret.read_text(encoding="utf-8").strip() == new_dsn


def test_init_force_replaces_https_shaped_local_entry_without_stray_keys(
    monkeypatch,
    machine_home,
    capsys,
):
    from yoke_cli.config import writer

    writer.set_connection(
        "local",
        transport="https",
        api_url="https://api.example",
        token="t" * 40,
    )
    monkeypatch.setattr(setup, "_engine", _stub_engine)

    assert commands.init(["--local", "--json"]) == 1
    assert "--force" in capsys.readouterr().err

    assert commands.init(["--local", "--force", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["connection"]["written"] is True

    entry = _config(machine_home)["connections"]["local"]
    assert entry["transport"] == "local-postgres"
    assert entry["prod"] is False
    assert entry["credential_source"]["kind"] == "dsn_file"
    # True replace: nothing from the https-shaped entry survives.
    assert set(entry) == {"transport", "prod", "credential_source"}


def test_init_requires_explicit_local_mode(capsys):
    assert commands.init([]) == 2
    assert "--local" in capsys.readouterr().err


def test_init_preserves_other_active_env_on_unchanged_rerun(
    monkeypatch,
    machine_home,
    capsys,
):
    monkeypatch.setattr(setup, "_engine", _stub_engine)
    assert commands.init(["--local", "--json"]) == 0
    capsys.readouterr()

    from yoke_cli.config import writer

    writer.set_connection(
        "stage",
        transport="https",
        api_url="https://api.example",
        token="t" * 40,
    )
    writer.set_active_env("stage")

    monkeypatch.setattr(setup, "_engine", lambda: _stub_engine(born=False))
    assert commands.init(["--local", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["connection"]["written"] is False
    assert _config(machine_home)["active_env"] == "stage"


def test_engine_setup_error_is_reported_cleanly(monkeypatch, machine_home, capsys):
    def failing_engine():
        return SimpleNamespace(
            birth=lambda org_name, emit: (_ for _ in ()).throw(
                _EngineError("embedded Postgres failed to start (exit 1)")
            ),
            LocalUniverseError=_EngineError,
        )

    monkeypatch.setattr(setup, "_engine", failing_engine)

    assert commands.init(["--local"]) == 1
    assert "embedded Postgres failed to start" in capsys.readouterr().err
