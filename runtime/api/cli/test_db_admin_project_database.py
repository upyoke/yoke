"""``yoke dev db-admin setup --database``: profiles for a project's own database."""

from __future__ import annotations

from runtime.api.cli.yoke_operations_cli_dev_db_admin_setup_test_support import (pytestmark as pytestmark)

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError

from runtime.api.cli.yoke_operations_cli_dev_db_admin_setup_test_support import (
    _env,
)

DECLARATION = {
    "default_model": "registry",
    "models": {
        "registry": {
            "authoritative_db": {
                "kind": "postgres",
                "location": {"database_name": "registry_db"},
            },
        },
        "media": {
            "authoritative_db": {
                "kind": "sqlite_file",
                "location": {"path": "app/data/media.db"},
            },
        },
    },
}


def _config(tmp_path: Path) -> Path:
    token_path = tmp_path / "tenant.token"
    token_path.write_text("sensitive-token\n", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "stage",
                "connections": {
                    "stage": {
                        "transport": "https",
                        "api_url": "https://tenant.example.com",
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(token_path),
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return config_path


def _settings(declaration) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function="projects.capability_settings.get",
        version="v1",
        result={"settings_json": json.dumps(declaration)},
    )


@pytest.fixture
def setup_env(tmp_path: Path, monkeypatch):
    from yoke_cli.config import db_admin_setup as config

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    relayed: list = []
    state = {"response": _settings(DECLARATION)}

    def relay(request, connection):
        relayed.append(request)
        return state["response"]

    monkeypatch.setattr(config.https_transport, "relay_https", relay)
    monkeypatch.setattr(
        config,
        "_resolve_environment",
        lambda project, env_name: _env(project=project, env_name=env_name),
    )
    monkeypatch.setattr(
        config,
        "_resolve_control_plane_database",
        lambda *_a, **_k: pytest.fail("declared database read the control plane's"),
    )
    return SimpleNamespace(config_path=_config(tmp_path), relayed=relayed, state=state)


def _setup(config_path: Path, *extra: str) -> int:
    return yoke_operations_cli.main(
        [
            "dev",
            "db-admin",
            "setup",
            "stage",
            "--database",
            "registry",
            "--config",
            str(config_path),
            *extra,
        ]
    )


def test_dry_run_plans_declared_database_on_the_box(setup_env, capsys):
    assert _setup(setup_env.config_path, "--dry-run", "--json") == 0

    payload = json.loads(capsys.readouterr().out)
    request = setup_env.relayed[0]
    assert request.function == "projects.capability_settings.get"
    assert request.payload == {"project": "yoke", "cap_type": "migration_model"}
    assert payload["plan"]["admin_env"] == "yoke-stage-registry-db-admin"
    assert payload["declared_database"]["database_name"] == "registry_db"
    assert "control_plane_database" not in payload
    assert payload["plan"]["authority"]["kind"] == "box_postgres"
    actions = [step["action"] for step in payload["plan"]["steps"]]
    assert actions[:2] == [
        "resolve-deploy-environment",
        "resolve-declared-database-location",
    ]
    assert actions[-2:] == ["forward-to-box-postgres", "configure-dsn-file-credential"]


@pytest.mark.parametrize("json_output", [True, False])
@pytest.mark.parametrize("admin_env", [None, "custom-registry-admin"])
def test_applied_database_profile_teaches_release_binding(
    setup_env, monkeypatch, capsys, json_output, admin_env
):
    from yoke_cli.config import db_admin_setup as config

    monkeypatch.setattr(config.box_mode, "apply", lambda *_a, **_kw: ({}, {}))
    monkeypatch.setattr(config, "_write_connection", lambda **_kw: {})
    extra = ["--yes"]
    if json_output:
        extra.append("--json")
    if admin_env:
        extra.extend(["--admin-env", admin_env])
    assert _setup(setup_env.config_path, *extra) == 0
    output = capsys.readouterr().out
    selected = admin_env or "yoke-stage-registry-db-admin"
    command = (
        "yoke projects environment-settings merge --project yoke "
        f"--environment stage --set release.admin_connection={selected}"
    )
    assert command in output
    if json_output:
        assert json.loads(output)["release_admin_connection_command"] == command


def test_missing_capability_refuses_with_declaration_teaching(setup_env, capsys):
    setup_env.state["response"] = FunctionCallResponse(
        success=False,
        function="projects.capability_settings.get",
        version="v1",
        error=FunctionError(code="not_found", message="no capability"),
    )

    assert _setup(setup_env.config_path, "--dry-run") == 1

    err = capsys.readouterr().err
    assert "no declared database location" in err
    assert "settings.models.registry.authoritative_db" in err


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("ledger", "declares no database model 'ledger' (declared: media, registry)"),
        ("media", "is a sqlite_file database"),
    ],
)
def test_undeclared_or_non_postgres_model_refuses(setup_env, capsys, model, expected):
    rc = yoke_operations_cli.main(
        [
            "dev",
            "db-admin",
            "setup",
            "stage",
            "--database",
            model,
            "--config",
            str(setup_env.config_path),
            "--dry-run",
        ]
    )

    assert rc == 1
    assert expected in capsys.readouterr().err


@pytest.mark.parametrize("action", ["--dry-run", "--yes"])
def test_model_without_database_name_refuses(setup_env, capsys, action):
    setup_env.state["response"] = _settings(
        {"models": {"registry": {"authoritative_db": {"kind": "postgres", "location": {}}}}}
    )
    assert _setup(setup_env.config_path, action) == 1
    err = capsys.readouterr().err
    assert "no declared database location" in err
    assert "missing location keys ['database_name']" in err
    assert "settings.models.registry.authoritative_db" in err
    assert "docs/public/databases/migration-model.md" in err
    assert "yoke-stage-registry-db-admin" not in json.loads(
        setup_env.config_path.read_text()
    )["connections"]
