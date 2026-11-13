"""CLI tests for ``yoke dev db-admin setup``."""

from __future__ import annotations

from runtime.api.cli.yoke_operations_cli_dev_db_admin_setup_test_support import (
    _env as _env,
    _identity_response as _identity_response,
    pytestmark as pytestmark,
)



from yoke_cli import main as yoke_operations_cli


def test_registry_and_inventory_track_dev_db_admin_setup() -> None:
    from yoke_cli import operation_inventory as inv
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS

    assert ("dev", "db-admin", "setup") not in SUBCOMMAND_REGISTRY
    assert ("dev", "db-admin", "setup") in TOOL_SHAPED_SUBCOMMANDS
    entry = inv.lookup("yoke dev db-admin setup")
    assert entry is not None
    assert entry.status == inv.PERMANENT
    assert entry.reason == inv.REASON_TOOL_SHAPED


def test_dev_db_admin_setup_refuses_render_only(monkeypatch, capsys) -> None:
    from yoke_cli.config import db_admin_setup as config

    monkeypatch.setattr(
        config,
        "_resolve_environment",
        lambda project, env_name: _env(
            project=project,
            env_name=env_name,
            activation_state="render_only",
        ),
    )
    monkeypatch.setattr(
        config,
        "_select_control_plane_env",
        lambda env_name, **_kwargs: env_name,
    )
    monkeypatch.setattr(
        config,
        "_resolve_control_plane_database",
        lambda control_plane_env, **_kwargs: "yoke_tenant_4",
    )

    rc = yoke_operations_cli.main(
        [
            "dev",
            "db-admin",
            "setup",
            "stage",
            "--yes",
        ]
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert "render_only" in err
    assert "stage-db-admin" in err
