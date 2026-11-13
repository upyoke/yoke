"""``yoke dev db-admin exec`` reaches a box profile's Postgres through its tunnel.

The profile is written by box-mode setup; the DSN comes from its ``dsn_file``
through the real engine resolver, and the managed SSH forward the readiness
path sees targets the box's own ``127.0.0.1:5432``.
"""

from __future__ import annotations

from runtime.api.cli.yoke_operations_cli_dev_db_admin_setup_test_support import (pytestmark as pytestmark)

import json
import sys
from types import SimpleNamespace

import pytest

from yoke_cli import main as yoke_operations_cli
from yoke_core.domain import connected_env_readiness_connector as connector
from yoke_core.domain import connected_env_readiness_tunnel as tunnel
from yoke_core.domain import yoke_connected_env

from runtime.api.cli.test_db_admin_box_mode import DSN, PASSWORD, _provision, _setup
from runtime.api.cli.test_db_admin_box_mode import box as box  # noqa: F401 - fixture

CHILD = (
    "import os, pathlib, sys; "
    "sys.exit(0 if os.environ['APP_DSN'] == "
    "pathlib.Path(sys.argv[1]).read_text().strip() else 3)"
)


@pytest.fixture
def forwards(monkeypatch):
    """Record the managed forward readiness would bring up; report it healthy."""
    seen: list = []

    def evaluate(*, allow_restart: bool):
        detection = connector.detect()
        seen.append(detection)
        return SimpleNamespace(ok=True, environment=detection.environment, message="ok")

    monkeypatch.setattr(tunnel, "evaluate", evaluate)
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.delenv("APP_DSN", raising=False)
    return seen


def test_exec_runs_with_the_box_dsn_through_the_box_forward(box, forwards, capsys) -> None:
    _provision(box.dsn_path)
    assert _setup(box.config_path, "--protected", "--yes") == 0
    capsys.readouterr()

    rc = yoke_operations_cli.main(
        [
            "dev", "db-admin", "exec", "stage-db-admin", "--dsn-var", "APP_DSN",
            "--", sys.executable, "-c", CHILD, str(box.dsn_path),
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert PASSWORD not in captured.out + captured.err
    [detection] = forwards
    assert detection.connector_kind == connector.CONNECTOR_LOCAL_SSH_TUNNEL_PG
    assert detection.environment == "stage-db-admin"
    assert (detection.local_host, detection.local_port) == ("127.0.0.1", 6548)
    assert detection.spec.bastion == "yoke-stage-box"
    assert detection.spec.ssh_config == str(box.home / "ssh" / "config")
    assert (detection.spec.remote_host, detection.spec.remote_port) == (
        "127.0.0.1",
        5432,
    )


def test_exec_names_a_missing_box_dsn_file(box, forwards, capsys) -> None:
    _provision(box.dsn_path)
    assert _setup(box.config_path, "--yes") == 0
    box.dsn_path.unlink()
    capsys.readouterr()

    rc = yoke_operations_cli.main(
        [
            "dev", "db-admin", "exec", "stage-db-admin", "--dsn-var", "APP_DSN",
            "--", sys.executable, "-c", "0",
        ]
    )

    captured = capsys.readouterr()
    assert rc != 0
    assert "profile_unusable" in captured.err
    assert str(box.dsn_path) in captured.err
    assert forwards == []
    assert json.loads(box.config_path.read_text())["connections"]["stage-db-admin"]
    assert DSN not in captured.err
