"""Tests for the source-dev/admin schema convergence command."""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from yoke_cli import operation_inventory as inv
from yoke_cli import product_boundary_inventory as boundary_inventory
from yoke_cli.commands.schema_converge import schema_converge
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_cli.main import main as cli_main


REPO_ROOT = Path(__file__).resolve().parents[3]
_CLOUD_AUTHORITY_MODULE = "yoke_core.domain.cloud_db_secret_dsn"
_SERVER_ENTRYPOINT_MODULE = "yoke_core.api.server_entrypoint"


def _core_module_loader(entrypoint, *, managed_secret: bool = False):
    def load(name: str):
        if name == _CLOUD_AUTHORITY_MODULE:
            return SimpleNamespace(
                DB_SECRET_ARN_ENV="YOKE_DB_SECRET_ARN",
                env_binding_selected=lambda: managed_secret,
            )
        if name == _SERVER_ENTRYPOINT_MODULE:
            return entrypoint
        raise ImportError(name)

    return load


def test_schema_converge_token_resolves() -> None:
    resolved = resolve_tool_shaped(["schema", "converge", "--json"])

    assert resolved is not None
    adapter, rest = resolved
    assert adapter is schema_converge
    assert rest == ["--json"]


def test_schema_converge_calls_boot_convergence_and_emits_json() -> None:
    calls: list[str] = []
    module = SimpleNamespace(
        ensure_core_schema=lambda: calls.append("converged"),
    )
    out, err = io.StringIO(), io.StringIO()

    with patch.dict(
        os.environ,
        {"YOKE_PG_DSN": "", "YOKE_PG_DSN_FILE": ""},
        clear=False,
    ), patch(
        "yoke_cli.config.machine_config.active_env",
        return_value="stage-db-admin",
    ), patch(
        "yoke_cli.commands.schema_converge.importlib.import_module",
        side_effect=_core_module_loader(module),
    ), redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(["schema", "converge", "--json"])

    assert rc == 0
    assert calls == ["converged"]
    assert json.loads(out.getvalue()) == {
        "authority_source": "connected_environment",
        "environment": "stage-db-admin",
        "ok": True,
        "operation": "schema.converge",
        "schema": "core",
    }
    assert err.getvalue() == ""


def test_schema_converge_failure_redacts_exception_message() -> None:
    secret = "postgresql://admin:do-not-print@example/yoke_prod"

    def fail() -> None:
        raise RuntimeError(secret)

    module = SimpleNamespace(ensure_core_schema=fail)
    out, err = io.StringIO(), io.StringIO()
    with patch.dict(
        os.environ,
        {"YOKE_PG_DSN": "", "YOKE_PG_DSN_FILE": ""},
        clear=False,
    ), patch(
        "yoke_cli.config.machine_config.active_env",
        return_value="stage-db-admin",
    ), patch(
        "yoke_cli.commands.schema_converge.importlib.import_module",
        side_effect=_core_module_loader(module),
    ), redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(["schema", "converge", "--json"])

    assert rc == 1
    assert out.getvalue() == ""
    assert secret not in err.getvalue()
    assert json.loads(err.getvalue()) == {
        "error": "schema_convergence_failed",
        "error_type": "RuntimeError",
        "ok": False,
        "operation": "schema.converge",
    }


def test_schema_converge_rejects_named_env_with_direct_dsn() -> None:
    secret = "postgresql://admin:do-not-print@example/yoke_prod"
    calls: list[str] = []
    module = SimpleNamespace(
        ensure_core_schema=lambda: calls.append("converged"),
    )
    out, err = io.StringIO(), io.StringIO()

    with patch.dict(
        os.environ,
        {"YOKE_PG_DSN": secret},
        clear=False,
    ), patch(
        "yoke_cli.commands.schema_converge.importlib.import_module",
        side_effect=_core_module_loader(module),
    ), redirect_stdout(out), redirect_stderr(err):
        rc = cli_main([
            "--env", "prod-db-admin", "schema", "converge", "--json",
        ])

    assert rc == 1
    assert calls == []
    assert out.getvalue() == ""
    assert secret not in err.getvalue()
    assert json.loads(err.getvalue()) == {
        "conflicting_environment_variables": ["YOKE_PG_DSN"],
        "environment": "prod-db-admin",
        "error": "schema_authority_conflict",
        "ok": False,
        "operation": "schema.converge",
    }


def test_schema_converge_rejects_named_env_with_managed_secret() -> None:
    secret = "arn:aws:secretsmanager:us-east-1:123456789012:secret:db"
    calls: list[str] = []
    module = SimpleNamespace(
        ensure_core_schema=lambda: calls.append("converged"),
    )
    out, err = io.StringIO(), io.StringIO()

    with patch.dict(
        os.environ,
        {
            "YOKE_DB_SECRET_ARN": secret,
            "YOKE_PG_DSN": "",
            "YOKE_PG_DSN_FILE": "",
        },
        clear=False,
    ), patch(
        "yoke_cli.commands.schema_converge.importlib.import_module",
        side_effect=_core_module_loader(module, managed_secret=True),
    ), redirect_stdout(out), redirect_stderr(err):
        rc = cli_main([
            "--env", "prod-db-admin", "schema", "converge", "--json",
        ])

    assert rc == 1
    assert calls == []
    assert out.getvalue() == ""
    assert secret not in err.getvalue()
    assert json.loads(err.getvalue()) == {
        "conflicting_environment_variables": ["YOKE_DB_SECRET_ARN"],
        "environment": "prod-db-admin",
        "error": "schema_authority_conflict",
        "ok": False,
        "operation": "schema.converge",
    }


def test_schema_converge_global_env_is_selected_then_restored() -> None:
    seen: list[str | None] = []
    module = SimpleNamespace(
        ensure_core_schema=lambda: seen.append(os.environ.get("YOKE_ENV")),
    )
    out, err = io.StringIO(), io.StringIO()

    with patch.dict(os.environ, {}, clear=True), patch(
        "yoke_cli.config.machine_config.active_env",
        side_effect=lambda *, explicit_env: explicit_env,
    ), patch(
        "yoke_cli.commands.schema_converge.importlib.import_module",
        side_effect=_core_module_loader(module),
    ), redirect_stdout(out), redirect_stderr(err):
        rc = cli_main([
            "--env", "prod-db-admin", "schema", "converge", "--json",
        ])
        restored = os.environ.get("YOKE_ENV")

    assert rc == 0
    assert seen == ["prod-db-admin"]
    assert restored is None
    assert json.loads(out.getvalue())["environment"] == "prod-db-admin"
    assert err.getvalue() == ""


def test_schema_converge_help_marks_source_dev_admin_surface() -> None:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cli_main(["schema", "converge", "--help"])

    assert rc == 0
    assert "source-dev/admin operation" in out.getvalue()
    assert "idempotent, additive schema convergence" in out.getvalue()
    assert err.getvalue() == ""


def test_schema_converge_is_registered_as_source_dev_admin() -> None:
    entry = inv.lookup("yoke schema converge")
    assert entry is not None
    assert entry.status == inv.PERMANENT
    assert entry.reason == inv.REASON_TOOL_SHAPED

    rows = {
        row.command_helper: row
        for row in boundary_inventory.generate_inventory(repo_root=REPO_ROOT)
    }
    row = rows["yoke schema converge"]
    assert row.disposition == boundary_inventory.SOURCE_DEV_ADMIN
    assert row.function_id is None
    assert {edge.classification for edge in row.import_edges} == {
        "source_dev_admin"
    }


def test_top_and_group_help_label_schema_converge_source_dev_admin() -> None:
    for args in (["--help"], ["schema", "--help"]):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli_main(args)
        assert rc == 0
        assert "yoke schema converge [source-dev/admin]" in out.getvalue()
