"""``yoke dev db-admin exec``: one subprocess gets a profile DSN, nothing else does."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import db_admin_dsn_exec as exec_mod

PASSWORD = "hunter2-never-shown"
DSN = f"host=127.0.0.1 port=6548 user=admin password={PASSWORD} dbname=registry_db"
PROFILE = "yoke-stage-registry-db-admin"


class SelectedPostgresError(RuntimeError):
    pass


class ConnectedEnvUnavailable(RuntimeError):
    pass


def _redact(text: str) -> str:
    return text.replace(f"password={PASSWORD}", "password=***")


@pytest.fixture
def engine(tmp_path: Path, monkeypatch):
    """A configured profile plus fake engine modules the runner reaches."""
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.delenv("REGISTRY_DSN", raising=False)
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "stage",
                "connections": {
                    "stage": {
                        "transport": "https",
                        "api_url": "https://tenant.example.com",
                    },
                    PROFILE: {
                        "transport": "local-postgres",
                        "prod": False,
                        "credential_source": {
                            "kind": "aws_secrets_manager",
                            "secret_arn": "arn:aws:secretsmanager:us-east-1:1:secret:r",
                            "region": "us-east-1",
                            "project": "yoke",
                        },
                        "postgres": {"host": "127.0.0.1", "port": 6548},
                        "authority": {
                            "kind": "aws_aurora_postgres",
                            "location": {
                                "stack": "yoke-stage",
                                "region": "us-east-1",
                                "database_name": "registry_db",
                            },
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    state = SimpleNamespace(
        activate=lambda env: SimpleNamespace(
            dsn=DSN, readiness=SimpleNamespace(ok=True, message="ok")
        ),
        aws_env=lambda project, region: {"AWS_REGION": region},
        activated=[],
    )

    def activate(env):
        state.activated.append(env)
        return state.activate(env)

    modules = {
        "yoke_core.domain.deploy_remote": SimpleNamespace(
            aws_machine_capability_env=lambda p, r: state.aws_env(p, r)
        ),
        "yoke_core.domain.connected_env_selected_readiness": SimpleNamespace(
            activate_selected_postgres=activate,
            SelectedPostgresError=SelectedPostgresError,
        ),
        "yoke_core.domain.connected_env_readiness_connector": SimpleNamespace(
            redact=_redact, ConnectedEnvUnavailable=ConnectedEnvUnavailable
        ),
    }
    monkeypatch.setattr(exec_mod, "import_module", modules.__getitem__)
    monkeypatch.setattr(
        exec_mod.aws_cli_prerequisite,
        "check_aws_cli",
        lambda: SimpleNamespace(executable="aws", version="aws-cli/2"),
    )
    return state


def _exec(*command: str, env: str = PROFILE) -> int:
    return yoke_operations_cli.main(
        ["dev", "db-admin", "exec", env, "--dsn-var", "REGISTRY_DSN", "--", *command]
    )


def test_registry_tracks_dev_db_admin_exec() -> None:
    from yoke_cli import operation_inventory as inv
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS

    assert ("dev", "db-admin", "exec") in TOOL_SHAPED_SUBCOMMANDS
    entry = inv.lookup("yoke dev db-admin exec")
    assert entry is not None and entry.reason == inv.REASON_TOOL_SHAPED


def test_child_alone_receives_dsn_and_nothing_prints_it(engine, capfd, caplog):
    caplog.set_level(logging.DEBUG)
    child = (
        "import os, sys; "
        f"sys.exit(0 if os.environ.get('REGISTRY_DSN') == {DSN!r} else 9)"
    )

    rc = _exec(sys.executable, "-c", child)

    out, err = capfd.readouterr()
    assert rc == 0
    assert engine.activated == [PROFILE]
    assert "REGISTRY_DSN" not in os.environ
    assert "YOKE_ENV" not in os.environ
    for surface in (out, err, caplog.text):
        assert PASSWORD not in surface


def test_child_exit_code_passes_through(engine) -> None:
    assert _exec(sys.executable, "-c", "raise SystemExit(7)") == 7


@pytest.mark.parametrize(
    ("setup", "env", "reason", "recovery"),
    [
        (None, "nope-db-admin", "profile_not_configured", "yoke env list"),
        (None, "stage", "profile_not_postgres", "yoke dev db-admin setup"),
        (
            lambda s: setattr(
                s,
                "aws_env",
                lambda p, r: (_ for _ in ()).throw(RuntimeError("no keys")),
            ),
            PROFILE,
            "aws_admin_capability_unavailable",
            "--cap-type aws-admin",
        ),
        (
            lambda s: setattr(
                s,
                "activate",
                lambda env: (_ for _ in ()).throw(
                    subprocess.CalledProcessError(
                        254, ["aws"], stderr="AccessDeniedException"
                    )
                ),
            ),
            PROFILE,
            "secret_unreadable",
            "secretsmanager describe-secret",
        ),
        (
            lambda s: setattr(
                s,
                "activate",
                lambda env: SimpleNamespace(
                    dsn=DSN,
                    readiness=SimpleNamespace(
                        ok=False, message=f"probe failed for {DSN}"
                    ),
                ),
            ),
            PROFILE,
            "database_unreachable",
            "bastion",
        ),
        (
            lambda s: setattr(
                s,
                "activate",
                lambda env: (_ for _ in ()).throw(ConnectedEnvUnavailable("ssh down")),
            ),
            PROFILE,
            "database_unreachable",
            "bastion",
        ),
    ],
)
def test_refusals_name_reason_and_recovery_without_dsn(
    engine, capfd, setup, env, reason, recovery
):
    if setup is not None:
        setup(engine)

    rc = _exec(sys.executable, "-c", "raise SystemExit(0)", env=env)

    out, err = capfd.readouterr()
    assert rc == 1
    assert f"error: {reason}:" in err
    assert "recovery:" in err and recovery in err
    assert PASSWORD not in out + err


def test_unrunnable_command_and_bad_variable_refuse(engine, capfd) -> None:
    assert _exec("definitely-not-a-command-on-path") == 127
    assert "command_not_runnable" in capfd.readouterr().err

    rc = yoke_operations_cli.main(
        ["dev", "db-admin", "exec", PROFILE, "--dsn-var", "1BAD", "--", "true"]
    )
    assert rc == 2
    assert "invalid_dsn_var" in capfd.readouterr().err
    assert engine.activated == [PROFILE]
