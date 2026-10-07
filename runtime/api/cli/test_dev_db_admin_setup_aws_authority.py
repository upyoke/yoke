"""``yoke dev db-admin setup`` resolves aws-admin from the machine store.

Applying setup runs on a machine whose active control plane is HTTPS, where
the selected database cannot be opened. The AWS credentials that read the
stack outputs therefore come from the machine-local capability store, and
the written profile carries only the managed-secret reference.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_cli.config.capability_secrets import store_machine_capability_secret
from yoke_contracts import control_plane_locality
from yoke_core.domain import deploy_core_container, deploy_remote

pytestmark = pytest.mark.usefixtures("bound_project_context")

SECRET_ARN = "arn:aws:secretsmanager:us-east-1:123456789012:secret:yoke-stage"


def _stub_setup_resolution(monkeypatch, config) -> None:
    monkeypatch.setattr(
        config,
        "_resolve_environment",
        lambda project, env_name: _env(project=project, env_name=env_name),
    )
    monkeypatch.setattr(
        config, "_select_control_plane_env", lambda env_name, **_kwargs: env_name
    )
    monkeypatch.setattr(
        config,
        "_resolve_control_plane_database",
        lambda control_plane_env, **_kwargs: "yoke_tenant_4",
    )


def _run_apply(config_path: Path) -> int:
    with control_plane_locality.remote_control_plane():
        return yoke_operations_cli.main(
            [
                "dev",
                "db-admin",
                "setup",
                "stage",
                "--config",
                str(config_path),
                "--yes",
                "--json",
            ]
        )


def test_apply_under_https_reads_aws_admin_from_machine_store(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from yoke_cli.config import db_admin_setup as config

    machine_home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "GITHUB_ACTIONS"):
        monkeypatch.delenv(name, raising=False)
    store_machine_capability_secret("yoke", "aws-admin", "access_key_id", "AKIAMACHINE")
    store_machine_capability_secret(
        "yoke", "aws-admin", "secret_access_key", "machine-secret-value"
    )
    _stub_setup_resolution(monkeypatch, config)
    monkeypatch.setattr(
        deploy_remote,
        "cmd_capability_get_secret",
        lambda *_args: pytest.fail("consulted the selected database"),
    )
    seen_env: dict[str, str] = {}

    def fake_binding(runner, env, aws_env, *, emit):
        seen_env.update(aws_env)
        return (
            SimpleNamespace(host="stage.cluster.internal", port=5432),
            {"databaseSecretArn": SECRET_ARN},
        )

    monkeypatch.setattr(
        deploy_core_container, "resolve_environment_database_binding", fake_binding
    )
    config_path = machine_home / "config.json"

    rc = _run_apply(config_path)

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert seen_env["AWS_ACCESS_KEY_ID"] == "AKIAMACHINE"
    assert seen_env["AWS_REGION"] == "us-east-1"
    assert json.loads(captured.out)["applied"] is True
    written = config_path.read_text(encoding="utf-8")
    assert "machine-secret-value" not in written
    assert "machine-secret-value" not in captured.out + captured.err
    entry = json.loads(written)["connections"]["stage-db-admin"]
    assert entry["credential_source"]["secret_arn"] == SECRET_ARN
    assert entry["postgres"]["tunnel"]["remote_host"] == "stage.cluster.internal"


def test_apply_without_machine_aws_admin_refuses_by_name(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from yoke_cli.config import db_admin_setup as config

    machine_home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(machine_home))
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "GITHUB_ACTIONS"):
        monkeypatch.delenv(name, raising=False)
    _stub_setup_resolution(monkeypatch, config)
    monkeypatch.setattr(
        deploy_core_container,
        "resolve_environment_database_binding",
        lambda *_a, **_k: pytest.fail("resolved the binding without credentials"),
    )
    config_path = machine_home / "config.json"

    rc = _run_apply(config_path)

    captured = capsys.readouterr()
    assert rc == 1
    assert "Traceback" not in captured.err
    assert "aws-admin authority from this machine's capability store" in captured.err
    assert "yoke projects capability secret set --project yoke" in captured.err
    assert not config_path.exists()


def _env(*, project: str, env_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        project=project,
        env_name=env_name,
        activation_state="active",
        stack_name=f"yoke-{env_name}",
        database_name=f"yoke_{env_name}",
        origin_host=f"origin.{env_name}.example.com",
        ssh_key_path=f"/tmp/yoke-{env_name}.pem",
        ssh_target=f"ubuntu@origin.{env_name}.example.com",
        aws_region="us-east-1",
    )
