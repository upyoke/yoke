"""Product-boundary coverage for local-core admin envs."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.test_yoke_product_boundary_fault_injection import (
    _run_product_cli,
)


def test_status_local_postgres_reports_missing_core_without_loading_it(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(
        tmp_path,
        ["status", "--json"],
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
    report = json.loads(run.stdout)
    assert report["connection"]["client_authority"] == "local-core"
    assert report["db"]["action"] == "local_postgres_core_unavailable"
    issue_codes = {issue["code"] for issue in report["issues"]}
    assert "import_missing" in issue_codes
    assert any(
        name == "yoke_core" or str(name).startswith("yoke_core.")
        for name in run.boundary["blocked_attempts"]
    )
    assert run.boundary["forbidden_loaded"] == []
    assert run.boundary["caught"] is None
