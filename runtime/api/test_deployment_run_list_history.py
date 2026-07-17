"""Bounded, recent-first deployment run history coverage."""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_runs


pytest_plugins = ["runtime.api.test_deployment_runs_full_helpers"]


def test_list_is_recent_first_and_bounded(db_path: str) -> None:
    first = deployment_runs.cmd_create_run(
        "yoke", "yoke-internal", db_path=db_path,
    )
    second = deployment_runs.cmd_create_run(
        "yoke", "yoke-internal", db_path=db_path,
    )
    third = deployment_runs.cmd_create_run(
        "yoke", "yoke-internal", db_path=db_path,
    )

    lines = deployment_runs.cmd_list(limit=2, db_path=db_path).splitlines()

    assert lines[0].startswith(f"{third}|")
    assert lines[1].startswith(f"{second}|")
    assert all(not line.startswith(f"{first}|") for line in lines)


def test_source_cli_accepts_history_limit(
    db_path: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    deployment_runs.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
    latest = deployment_runs.cmd_create_run(
        "yoke", "yoke-internal", db_path=db_path,
    )

    return_code = deployment_runs.main(["list", "--limit", "1"])

    assert return_code == 0
    assert capsys.readouterr().out.startswith(f"{latest}|")
