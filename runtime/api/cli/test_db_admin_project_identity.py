"""DB-admin setup keys the profile DSN file by canonical project."""

import pytest

from yoke_cli.config import db_admin_setup as config
from runtime.api.cli.yoke_operations_cli_dev_db_admin_setup_test_support import (
    _env,
)


@pytest.mark.parametrize("project", [None, "7", "acme"])
def test_dsn_file_label_uses_resolved_environment_project(monkeypatch, project):
    monkeypatch.setattr(config, "required_project_context", lambda ref: ref or "7")
    monkeypatch.setattr(
        config, "_resolve_environment", lambda *args: _env(project="acme")
    )
    monkeypatch.setattr(
        config, "_select_control_plane_env", lambda *args, **kwargs: "prod"
    )
    monkeypatch.setattr(
        config, "_resolve_control_plane_database", lambda *args, **kwargs: "tenant"
    )
    report = config.build_report(
        env_name="prod",
        project=project,
        config_path=None,
        admin_env=None,
        local_port=None,
        secret_label=None,
        control_plane_env=None,
        apply=False,
        set_active_env=False,
        allow_render_only=False,
    )
    assert report["project"] == "acme"
    assert report["plan"]["dsn_file"].endswith(
        "secrets/acme-prod-db-admin.dsn"
    )
