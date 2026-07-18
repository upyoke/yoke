"""Fault-injection tests for the installable Yoke product CLI boundary."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.product_boundary_test_support import (
    REPO_ROOT,
    _assert_clean_client_boundary,
    _run_product_cli,
)



def test_version_does_not_import_source_authority(tmp_path: Path) -> None:
    run = _run_product_cli(tmp_path, ["--version"])

    assert run.returncode == 0
    assert run.stdout.strip() == "source"
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_top_level_help_does_not_import_source_authority(tmp_path: Path) -> None:
    run = _run_product_cli(tmp_path, ["--help"])

    assert run.returncode == 0
    assert "Available subcommands" in run.stdout
    assert "yoke status" in run.stdout
    assert "yoke project install" in run.stdout
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_status_missing_config_reports_locally_without_authority_import(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(tmp_path, ["status", "--json"])

    assert run.returncode == 1
    report = json.loads(run.stdout)
    assert report["ok"] is False
    assert report["repo_root"] == run.boundary["cwd"]
    issue_codes = {issue["code"] for issue in report["issues"]}
    assert "config_missing" in issue_codes
    assert "connections_required" in issue_codes
    assert set(report["runtime"]["package_versions"].values()) == {""}
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_product_local_help_commands_do_not_import_source_authority(
    tmp_path: Path,
) -> None:
    commands = (
        (("db", "read", "--help"), "usage: yoke db read"),
        (("onboard", "--help"), "usage: yoke onboard"),
        (("project", "install", "--help"), "usage: yoke project install"),
        (("dev", "setup", "--help"), "usage: yoke dev setup"),
        (
            ("dev", "path-snapshot-prewarm", "--help"),
            "usage: yoke dev path-snapshot-prewarm",
        ),
        (
            ("readiness", "prd-validate", "--help"),
            "usage: yoke readiness prd-validate",
        ),
    )

    for args, expected_usage in commands:
        run = _run_product_cli(tmp_path / "-".join(args), args)
        assert run.returncode == 0
        assert expected_usage in run.stdout
        assert run.stderr == ""
        _assert_clean_client_boundary(run)


def test_db_read_dispatch_fails_closed_at_existing_local_boundary(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(tmp_path, ["db", "read", "SELECT 1", "--json"])

    assert run.returncode == 1
    response = json.loads(run.stdout)
    assert response["function"] == "db.read.run"
    assert response["success"] is False
    assert response["error"]["code"] == "local_postgres_core_unavailable"
    assert any(
        name == "yoke_core" or str(name).startswith("yoke_core.")
        for name in run.boundary["blocked_attempts"]
    )
    assert run.boundary["forbidden_loaded"] == []
    assert run.boundary["caught"] is None


def test_db_read_prod_flagged_local_postgres_requires_core_import(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(
        tmp_path,
        ["db", "read", "SELECT 1", "--json"],
        config_payload={
            "schema_version": 1,
            "active_env": "prod-db-admin",
            "connections": {
                "prod-db-admin": {
                    "transport": "local-postgres",
                    "prod": True,
                },
            },
        },
    )

    assert run.returncode == 1
    response = json.loads(run.stdout)
    assert response["function"] == "db.read.run"
    assert response["success"] is False
    assert response["error"]["code"] == "local_postgres_core_unavailable"
    assert "yoke-core engine" in response["error"]["message"]
    assert any(
        name == "yoke_core" or str(name).startswith("yoke_core.")
        for name in run.boundary["blocked_attempts"]
    )
    assert run.boundary["forbidden_loaded"] == []
    assert run.boundary["caught"] is None


def test_local_only_dispatch_fails_closed_when_core_authority_is_blocked(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(tmp_path, ["agents", "render", "--json"])

    assert run.returncode == 1
    response = json.loads(run.stdout)
    assert response["success"] is False
    assert response["error"]["code"] == "local_postgres_core_unavailable"
    assert "yoke-core engine" in response["error"]["message"]
    assert "yoke env use" in response["error"]["recovery_hint"]
    assert any(
        name == "yoke_core" or str(name).startswith("yoke_core.")
        for name in run.boundary["blocked_attempts"]
    )
    assert run.boundary["forbidden_loaded"] == []
    assert run.boundary["caught"] is None
    assert "Traceback" not in run.stderr


def test_ordinary_packaged_refresh_does_not_import_core(
    tmp_path: Path,
) -> None:
    target = tmp_path / "external-project"
    target.mkdir()
    run = _run_product_cli(
        tmp_path,
        [
            "project", "refresh", str(target), "--project-id", "7",
            "--config", str(tmp_path / "home/.yoke/config.json"),
        ],
        config_payload={
            "schema_version": 1,
            "active_env": "product",
            "connections": {
                "product": {
                    "transport": "https",
                    "api_url": "http://127.0.0.1:1",
                    "credential_source": {
                        "kind": "token_env",
                        "env_var": "YOKE_TEST_TOKEN",
                    },
                },
            },
        },
    )

    assert run.returncode == 1
    assert "yoke_core" not in run.boundary["blocked_attempts"]
    assert not any(
        str(name).startswith("yoke_core.")
        for name in run.boundary["blocked_attempts"]
    )
    assert run.boundary["forbidden_loaded"] == []
    assert not (target / ".yoke/install-manifest.json").exists()


def test_status_fails_when_hook_runtime_package_is_missing(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(
        tmp_path,
        ["status", "--json"],
        include_harness=False,
    )

    report = json.loads(run.stdout)
    assert run.returncode == 1
    assert any(
        issue["code"] == "import_missing"
        and "yoke_harness" in issue["message"]
        for issue in report["issues"]
    )


def test_source_refresh_preview_diagnoses_without_hook_runtime(
    tmp_path: Path,
) -> None:
    target = tmp_path / "external-project"
    target.mkdir()
    run = _run_product_cli(
        tmp_path,
        [
            "project", "refresh", str(target),
            "--source-checkout", str(REPO_ROOT),
            "--project-id", "8",
            "--project-slug", "preview-project",
            "--json",
        ],
        include_harness=False,
    )

    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["preview"] is True
    assert report["target_writes"] is False
    assert run.boundary["blocked_attempts"] == []
    assert run.boundary["forbidden_loaded"] == []
    assert not (target / ".yoke/install-manifest.json").exists()
