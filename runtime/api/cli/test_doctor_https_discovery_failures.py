"""Client-side https doctor reports project-check import failures as FAIL."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from yoke_core.engines.doctor_https_only import run_local_project_checks
from yoke_core.engines.doctor_project_checks import Discovery, DiscoveryFailure
from yoke_core.engines.doctor_registry_types import HealthCheck


def test_run_local_project_checks_records_import_failures() -> None:
    project_hc = HealthCheck(
        slug="ok-check",
        name="Ok",
        fn=lambda *_a, **_k: None,
    )
    failure = DiscoveryFailure(
        path=Path("/target/.yoke/doctor/check_broken.py"),
        error="SyntaxError: invalid syntax",
    )
    with (
        patch(
            "yoke_core.engines.doctor_https_only.checkout_root_for_project",
            return_value=Path("/target/yoke"),
        ),
        patch(
            "yoke_core.engines.doctor_https_only.discover_project_checks",
            return_value=Discovery([project_hc], [failure]),
        ),
        patch(
            "yoke_core.engines.doctor_https_only.local_connection_or_none",
            return_value=None,
        ),
        patch(
            "yoke_core.engines.doctor_https_only.execute_check_isolated",
        ),
    ):
        rows = run_local_project_checks(project="yoke", slugs=["ok-check"])

    fail_rows = [row for row in rows if row["severity"] == "FAIL"]
    assert fail_rows
    assert fail_rows[0]["hc"] == "HC-project-check-discovery"
    assert "check_broken.py" in fail_rows[0]["detail"]
    assert "failed to import" in fail_rows[0]["detail"]
