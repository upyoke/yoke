"""``yoke dev db-admin setup`` box mode: Postgres on the environment's own box."""

from __future__ import annotations

from runtime.api.cli.yoke_operations_cli_dev_db_admin_setup_test_support import (pytestmark as pytestmark)

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import machine_config
from yoke_contracts.machine_config import schema as contract

from runtime.api.cli.test_db_admin_project_database import _config, _settings
from runtime.api.cli.yoke_operations_cli_dev_db_admin_setup_test_support import (
    _env,
)
from runtime.api.cli.test_db_admin_box_hop import MAC_FINGERPRINT, fake_hop

PASSWORD = "box-password-never-shown"
DSN = f"postgresql://yoke_admin:{PASSWORD}@127.0.0.1:6548/yoke_tenant_4"


def _box_env(project: str = "yoke", env_name: str = "stage") -> SimpleNamespace:
    env = _env(project=project, env_name=env_name)
    env.database_location = "box"
    env.mac_host = "testy@mac-mini"
    env.mac_host_ssh_key_path = "~/.ssh/operator_rsa"
    env.mac_host_key_fingerprint = MAC_FINGERPRINT
    env.ssh_user = "ubuntu"
    return env


@pytest.fixture
def box(tmp_path: Path, monkeypatch):
    from yoke_cli.config import db_admin_setup as config

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.setattr(
        config, "_resolve_environment", lambda project, env_name: _box_env(project, env_name)
    )
    monkeypatch.setattr(config, "_select_control_plane_env", lambda env_name, **_k: env_name)
    monkeypatch.setattr(
        config, "_resolve_control_plane_database", lambda *_a, **_k: "yoke_tenant_4"
    )
    monkeypatch.setattr(
        config,
        "_resolve_environment_database_binding",
        lambda *_a, **_k: pytest.fail("box mode looked up Pulumi outputs"),
    )
    monkeypatch.setattr(
        config,
        "_managed_credential_source",
        lambda *_a, **_k: pytest.fail("box mode looked up Secrets Manager"),
    )
    dsn_path = tmp_path / "secrets" / "yoke-stage-db-admin.dsn"
    calls = fake_hop(monkeypatch)
    return SimpleNamespace(
        home=tmp_path, config_path=_config(tmp_path), dsn_path=dsn_path, calls=calls
    )


def _provision(path: Path, dsn: str = DSN) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(dsn + "\n", encoding="utf-8")
    path.chmod(0o600)


def _setup(config_path: Path, *extra: str) -> int:
    return yoke_operations_cli.main(
        ["dev", "db-admin", "setup", "stage", "--config", str(config_path), *extra, "--json"]
    )


def test_box_plan_targets_box_postgres_and_keeps_the_dsn_file(box, capsys) -> None:
    assert _setup(box.config_path) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["applied"] is False
    assert report["plan"]["authority"] == {
        "kind": "box_postgres",
        "location": {
            "origin_host": "origin.stage.example.com",
            "database_name": "yoke_tenant_4",
        },
    }
    tunnel = report["plan"]["postgres"]["tunnel"]
    assert tunnel["remote_host"] == "127.0.0.1"
    assert tunnel["remote_port"] == 5432
    assert tunnel["bastion"] == "yoke-stage-box"
    assert tunnel["ssh_config"] == str(box.home / "ssh" / "config")
    actions = [step["action"] for step in report["plan"]["steps"]]
    assert actions == [
        "resolve-deploy-environment",
        "ensure-box-operator-key",
        "pin-mac-host-key",
        "authorize-box-operator-key",
        "pin-box-host-key",
        "write-box-ssh-config",
        "forward-to-box-postgres",
        "configure-dsn-file-credential",
    ]
    assert box.calls == [], "a plan must not touch the key or the Mac host"
    assert "remove-superseded-dsn-snapshot" not in actions
    assert "superseded_secret_path" not in report["plan"]
    assert report["plan"]["dsn_file"] == str(box.dsn_path)


def test_box_apply_writes_valid_protected_local_postgres_profile(box, capsys) -> None:
    _provision(box.dsn_path)

    assert _setup(box.config_path, "--protected", "--yes") == 0

    captured = capsys.readouterr()
    assert PASSWORD not in captured.out + captured.err
    report = json.loads(captured.out)
    assert report["applied"] is True
    assert report["box_hop"]["alias"] == "yoke-stage-box"
    assert report["box_hop"]["operator_key_created"] is True
    assert "superseded_dsn_snapshot_removed" not in report
    assert box.dsn_path.read_text(encoding="utf-8").strip() == DSN
    payload = json.loads(box.config_path.read_text(encoding="utf-8"))
    assert [
        issue for issue in contract.validate_payload(payload) if issue.severity == "error"
    ] == []
    entry = payload["connections"]["stage-db-admin"]
    assert entry == {
        "transport": "local-postgres",
        "protected": True,
        "credential_source": {"kind": "dsn_file", "path": str(box.dsn_path)},
        "postgres": {
            "host": "127.0.0.1",
            "port": 6548,
            "tunnel": {
                "kind": "ssh",
                "bastion": "yoke-stage-box",
                "identity_file": str(
                    box.home / "secrets" / "yoke-stage-box-operator-ssh-key"
                ),
                "ssh_config": str(box.home / "ssh" / "config"),
                "remote_host": "127.0.0.1",
                "remote_port": 5432,
            },
        },
        "authority": {
            "kind": "box_postgres",
            "location": {
                "origin_host": "origin.stage.example.com",
                "database_name": "yoke_tenant_4",
            },
        },
    }
    selected = machine_config.active_connection(
        box.config_path, explicit_env="stage-db-admin"
    )
    assert selected["transport"] in contract.POSTGRES_TRANSPORTS


def test_box_apply_refuses_without_a_provisioned_dsn_file(box, capsys) -> None:
    assert _setup(box.config_path, "--yes") != 0

    captured = capsys.readouterr()
    assert "box_dsn_file_unavailable" in captured.err
    assert box.calls == [], "the DSN refusal comes before any key or remote step"
    assert str(box.dsn_path) in captured.err
    assert "127.0.0.1:6548/yoke_tenant_4" in captured.err
    payload = json.loads(box.config_path.read_text(encoding="utf-8"))
    assert "stage-db-admin" not in payload["connections"]


def test_box_secret_name_selects_the_dsn_file(box, capsys) -> None:
    other = box.home / "secrets" / "custody-stage.dsn"
    _provision(other)

    assert _setup(box.config_path, "--secret-name", "custody-stage", "--yes") == 0

    report = json.loads(capsys.readouterr().out)
    source = report["admin_connection"]["connection"]["credential_source"]
    assert source == {"kind": "dsn_file", "path": str(other)}


@pytest.mark.parametrize("apply", [False, True])
def test_box_declared_database_needs_only_its_name(box, monkeypatch, capsys, apply) -> None:
    from yoke_cli.config import db_admin_setup as config
    from yoke_core.domain.migration_model_capability import validate
    from runtime.api.domain.test_migration_model_capability_postgres import _postgres_model

    declaration = validate({
        "models": {"registry": _postgres_model({"database_name": "registry_db"})},
    })

    monkeypatch.setattr(
        config.https_transport,
        "relay_https",
        lambda request, connection: _settings(declaration),
    )
    dsn_path = box.home / "secrets" / "yoke-stage-registry-db-admin.dsn"
    _provision(dsn_path, DSN.replace("yoke_tenant_4", "registry_db"))

    action = "--yes" if apply else "--dry-run"
    assert _setup(box.config_path, "--database", "registry", action) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["applied"] is apply
    if not apply:
        authority = report["plan"]["authority"]
        assert authority["kind"] == "box_postgres"
        assert authority["location"]["database_name"] == "registry_db"
        assert report["plan"]["postgres"]["tunnel"]["remote_host"] == "127.0.0.1"
        assert "yoke-stage-registry-db-admin" not in json.loads(
            box.config_path.read_text()
        )["connections"]
        return
    entry = report["admin_connection"]["connection"]
    assert report["admin_connection"]["env"] == "yoke-stage-registry-db-admin"
    assert entry["credential_source"] == {"kind": "dsn_file", "path": str(dsn_path)}
    assert entry["authority"]["location"]["database_name"] == "registry_db"
    assert entry["postgres"]["tunnel"]["remote_host"] == "127.0.0.1"
    assert report["declared_database"]["endpoint_output"] == ""


@pytest.mark.parametrize(
    ("database", "expected"),
    [({"name": "yoke_prod"}, "aurora"), ({"name": "yoke_prod", "location": "box"}, "box")],
)
def test_environment_database_location_setting(database, expected) -> None:
    from yoke_core.domain.deploy_environment_settings import (
        deploy_environment_from_settings,
    )
    from runtime.api.domain.test_deploy_environment_git_branch import (
        _full_capabilities,
        _prod_env,
        _settings as _project_settings,
    )

    env = deploy_environment_from_settings(
        _project_settings(
            environments=[_prod_env(database=database)],
            capabilities=_full_capabilities(),
        ),
        "prod",
    )
    assert env.database_location == expected


def test_environment_database_location_refuses_unknown_value() -> None:
    from yoke_core.domain.deploy_environment_settings import (
        DeployEnvironmentError,
        deploy_environment_from_settings,
    )
    from runtime.api.domain.test_deploy_environment_git_branch import (
        _full_capabilities,
        _prod_env,
        _settings as _project_settings,
    )

    with pytest.raises(DeployEnvironmentError, match="database.location 'rds'"):
        deploy_environment_from_settings(
            _project_settings(
                environments=[_prod_env(database={"name": "x", "location": "rds"})],
                capabilities=_full_capabilities(),
            ),
            "prod",
        )
