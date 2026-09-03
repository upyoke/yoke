"""Source commands cannot inherit a machine-administering DB selection."""

from __future__ import annotations

import json
from types import SimpleNamespace

from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_core.domain import administered_postgres
from yoke_core.tools import source_dev_run

ADMIN_ENV = "prod-db-admin"
SERVED_ENV = "prod"


def test_source_command_child_drops_administering_machine_authority(
    monkeypatch, tmp_path
) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "active_env": SERVED_ENV,
                "connections": {
                    SERVED_ENV: {"transport": "https"},
                    ADMIN_ENV: {
                        "transport": "local-postgres",
                        "prod": True,
                        "postgres": {"host": "127.0.0.1", "port": 6547},
                    },
                },
            }
        )
    )
    monkeypatch.setenv(machine_config_runtime.CONFIG_FILE_ENV, str(config))
    monkeypatch.setenv(ENV_OVERRIDE, ADMIN_ENV)
    monkeypatch.setattr(
        source_dev_run,
        "_claimed_root",
        lambda *_args: (tmp_path, None, None),
    )
    monkeypatch.setattr(
        source_dev_run._source_pythonpath,
        "import_origins",
        lambda _root, env: ({"runtime": str(tmp_path / "runtime")}, None),
    )
    captured = {}

    def launch(args, *, cwd, env, check):
        captured.update(args=args, cwd=cwd, env=env, check=check)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(source_dev_run.subprocess, "run", launch)

    assert source_dev_run.run(["python3", "-m", "pytest", "one_test.py"]) == 0

    child_env = captured["env"]
    assert child_env[ENV_OVERRIDE] == SERVED_ENV
    assert child_env[machine_config_runtime.HOME_ENV] != str(
        machine_config_runtime.yoke_home()
    )
    assert machine_config_runtime.CONFIG_FILE_ENV not in child_env
    inventory = child_env[administered_postgres.ADMINISTERED_TARGETS_ENV]
    assert "prod-db-admin" in inventory
    assert "6547" in inventory
    assert ADMIN_ENV not in {
        child_env.get(ENV_OVERRIDE),
        child_env.get("YOKE_PG_DSN"),
    }
