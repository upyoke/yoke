"""Local Postgres lifecycle, demo seed, and command routing."""

import json
import os

from yoke_cli.commands import local_universe as commands
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.config import local_universe_setup as setup
from runtime.api.cli.local_universe_cli_test_support import (
    _stub_engine,
    machine_home as machine_home,
)


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
                {"public_ref": "LOC-1", "title": "One"},
                {"public_ref": "LOC-2", "title": "Two"},
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
    assert [item["public_ref"] for item in report["items"]] == ["LOC-1", "LOC-2"]


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
