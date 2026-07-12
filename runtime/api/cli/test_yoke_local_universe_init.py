"""Tests for ``yoke init --local`` and the ``yoke local-postgres`` family.

The engine half is stubbed at the dynamic-import seam
(``local_universe_setup._engine``); these tests pin the client half:
machine-config connection writes, DSN secret storage, idempotency, the
no-clobber guard, and tool-shaped command resolution.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from yoke_cli.commands import local_universe as commands
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.config import local_universe_setup as setup


class _EngineError(RuntimeError):
    pass


def _stub_engine(
    *,
    born: bool = True,
    dsn: str = "host=/sock user=yoke dbname=yoke",
    socket_dsn_aliases: tuple[str, ...] = (),
):
    report = {
        "born": born,
        "cluster": {"root": "/machine-home/local-universe", "running": True},
        "dsn": dsn,
        "socket_dsn_aliases": list(socket_dsn_aliases),
        "org": {"slug": "default", "name": "Default Org"},
        "human_actor_id": 1,
    }
    if born:
        report["verified"] = {"organizations": 1, "actors": 1}
    return SimpleNamespace(
        birth=lambda org_name, emit: dict(report),
        start=lambda emit: {"running": True},
        stop=lambda: {"running": False},
        status=lambda: {"running": False, "initialized": True},
        LocalUniverseError=_EngineError,
    )


@pytest.fixture()
def machine_home(monkeypatch, tmp_path) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def _config(home: Path) -> dict:
    return json.loads((home / "config.json").read_text(encoding="utf-8"))


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


def test_local_postgres_lifecycle_routes_to_engine(monkeypatch, machine_home, capsys):
    monkeypatch.setattr(setup, "_engine", _stub_engine)

    assert commands.local_postgres_status(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["running"] is False
    assert commands.local_postgres_start(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["running"] is True
    assert commands.local_postgres_stop(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["running"] is False


def test_local_demo_seed_uses_non_prod_local_connection(
    monkeypatch,
    machine_home,
    capsys,
):
    dsn = machine_home / "secrets" / "local.dsn"
    dsn.parent.mkdir(parents=True)
    dsn.write_text("host=/sock user=yoke dbname=yoke\n", encoding="utf-8")
    (machine_home / "config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "local",
                "connections": {
                    "local": {
                        "transport": "local-postgres",
                        "prod": False,
                        "credential_source": {
                            "kind": "dsn_file",
                            "path": str(dsn),
                        },
                    },
                },
                "settings": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    from yoke_core.domain import local_demo_seed

    def _fake_seed(*, project, count):
        assert project == "1"
        assert count == 2
        assert os.environ["YOKE_PG_DSN_FILE"] == str(dsn)
        assert "YOKE_PG_DSN" not in os.environ
        return {
            "ok": True,
            "items": [
                {"item_ref": "LOC-1", "title": "One"},
                {"item_ref": "LOC-2", "title": "Two"},
            ],
            "next_step": "run board",
        }

    monkeypatch.setattr(local_demo_seed, "seed_demo_items", _fake_seed)

    assert (
        commands.local_demo_seed(
            [
                "--project",
                "1",
                "--count",
                "2",
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert [item["item_ref"] for item in report["items"]] == ["LOC-1", "LOC-2"]


def test_local_demo_seed_refuses_prod_local_connection(
    monkeypatch,
    machine_home,
    capsys,
):
    dsn = machine_home / "secrets" / "prod.dsn"
    dsn.parent.mkdir(parents=True)
    dsn.write_text("host=/sock user=yoke dbname=yoke_prod\n", encoding="utf-8")
    (machine_home / "config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod-db-admin",
                "connections": {
                    "prod-db-admin": {
                        "transport": "local-postgres",
                        "prod": True,
                        "credential_source": {
                            "kind": "dsn_file",
                            "path": str(dsn),
                        },
                    },
                },
                "settings": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert commands.local_demo_seed(["--json"]) == 1
    assert "prod-marked" in capsys.readouterr().err


def test_tool_shaped_resolution_covers_init_and_lifecycle():
    resolved = resolve_tool_shaped(["init", "--local"])
    assert resolved is not None and resolved[0] is commands.init

    resolved = resolve_tool_shaped(["local", "demo", "seed"])
    assert resolved is not None and resolved[0] is commands.local_demo_seed

    resolved = resolve_tool_shaped(["local-postgres", "start"])
    assert resolved is not None and resolved[0] is commands.local_postgres_start
