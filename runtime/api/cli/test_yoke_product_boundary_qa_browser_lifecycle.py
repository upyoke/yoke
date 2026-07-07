"""Product-boundary checks for Browser QA setup/status commands."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.test_yoke_product_boundary_fault_injection import (
    _assert_clean_client_boundary,
    _run_product_cli,
)


def test_qa_browser_group_help_lists_setup_and_status_without_source_import(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(tmp_path, ["qa", "browser", "--help"])

    assert run.returncode == 0
    assert "yoke qa browser setup" in run.stdout
    assert "yoke qa browser status" in run.stdout
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_qa_browser_status_runs_from_clean_client(tmp_path: Path) -> None:
    run = _run_product_cli(tmp_path, ["qa", "browser", "status", "--json"])

    assert run.returncode == 0
    payload = json.loads(run.stdout)
    assert payload["daemon"]["status"] == "not_running"
    assert payload["runtime_dir"].endswith("/home/.yoke/browser-runtime")
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_qa_browser_setup_dry_run_runs_from_clean_client(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(
        tmp_path, ["qa", "browser", "setup", "--dry-run", "--json"],
    )

    assert run.returncode == 0
    payload = json.loads(run.stdout)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["daemon"]["status"] == "not_running"
    assert payload["runtime_dir"].endswith("/home/.yoke/browser-runtime")
    assert run.stderr == ""
    _assert_clean_client_boundary(run)
