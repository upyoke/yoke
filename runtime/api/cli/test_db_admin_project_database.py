"""``yoke dev db-admin setup --database``: profiles for a project's own database."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError

from runtime.api.cli.test_yoke_operations_cli_dev_db_admin_setup import (
    _env,
    pytestmark,  # noqa: F401
)

REGISTRY_SECRET_ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:registry"
DECLARATION = {
    "default_model": "registry",
    "models": {
        "registry": {
            "authoritative_db": {
                "kind": "postgres",
                "location": {
                    "stack": "yoke-prod",
                    "database_name": "registry_db",
                    "endpoint_output": "registryEndpoint",
                    "secret_arn_output": "registrySecretArn",
                },
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
    monkeypatch.setattr(
        config,
        "_resolve_environment_database_binding",
        lambda env, emit=None: (
            SimpleNamespace(host="yoke.cluster.internal", port=5432),
            {
                "databaseClusterEndpoint": "yoke.cluster.internal",
                "databaseSecretArn": "arn:control-plane",
                "registryEndpoint": "registry.cluster.internal",
                "registrySecretArn": REGISTRY_SECRET_ARN,
            },
        ),
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


def test_dry_run_plans_declared_database_without_cloud_reads(setup_env, capsys):
    assert _setup(setup_env.config_path, "--dry-run", "--json") == 0

    payload = json.loads(capsys.readouterr().out)
    request = setup_env.relayed[0]
    assert request.function == "projects.capability_settings.get"
    assert request.payload == {"project": "yoke", "cap_type": "migration_model"}
    assert payload["plan"]["admin_env"] == "yoke-stage-registry-db-admin"
    assert payload["declared_database"]["database_name"] == "registry_db"
    assert "control_plane_database" not in payload
    assert "superseded_secret_path" not in payload["plan"]
    assert [step["action"] for step in payload["plan"]["steps"]] == [
        "resolve-deploy-environment",
        "resolve-declared-database-location",
        "resolve-non-secret-cloud-database-binding",
        "configure-managed-secret-authority",
    ]


def test_apply_writes_secretless_profile_from_declared_outputs(
    setup_env, tmp_path: Path, capsys
):
    assert _setup(setup_env.config_path, "--yes", "--json") == 0

    capsys.readouterr()
    entry = json.loads(setup_env.config_path.read_text(encoding="utf-8"))[
        "connections"
    ]["yoke-stage-registry-db-admin"]
    assert entry["transport"] == "local-postgres"
    assert entry["credential_source"] == {
        "kind": "aws_secrets_manager",
        "secret_arn": REGISTRY_SECRET_ARN,
        "region": "us-east-1",
        "project": "yoke",
    }
    assert entry["postgres"]["tunnel"]["remote_host"] == "registry.cluster.internal"
    assert entry["authority"]["location"] == {
        "stack": "yoke-stage",
        "region": "us-east-1",
        "database_name": "registry_db",
    }
    # The existing HTTPS control-plane connection is untouched.
    connections = json.loads(setup_env.config_path.read_text())["connections"]
    assert connections["stage"]["transport"] == "https"
    assert not list(tmp_path.rglob("*.dsn"))


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


def test_missing_declared_output_refuses_by_name(setup_env, monkeypatch, capsys):
    from yoke_cli.config import db_admin_setup as config

    monkeypatch.setattr(
        config,
        "_resolve_environment_database_binding",
        lambda env, emit=None: (
            SimpleNamespace(host="yoke.cluster.internal", port=5432),
            {"registryEndpoint": "registry.cluster.internal"},
        ),
    )

    assert _setup(setup_env.config_path, "--yes") == 1

    err = capsys.readouterr().err
    assert "outputs are missing registrySecretArn" in err
    assert (
        "yoke-stage-registry-db-admin"
        not in json.loads(setup_env.config_path.read_text())["connections"]
    )
