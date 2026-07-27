"""Product-boundary fault injection for ``yoke qa browser``."""

from __future__ import annotations

from pathlib import Path

from runtime.api.cli.product_boundary_test_support import (
    CLI_SRC,
    CONTRACTS_SRC,
    _assert_clean_client_boundary,
    _repo_pythonpath,
    _run_product_cli,
)

def test_qa_browser_help_does_not_import_source_authority(tmp_path: Path) -> None:
    run = _run_product_cli(
        tmp_path,
        ["qa", "browser", "screenshot", "--help"],
    )

    assert run.returncode == 0
    assert "usage: yoke qa browser screenshot" in run.stdout
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_aggregate_qa_browser_run_is_not_a_product_command(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(
        tmp_path,
        [
            "qa",
            "browser",
            "run",
            "--item",
            "EXT-1732",
            "--project",
            "externalwebapp",
            "--base-url",
            "http://127.0.0.1:1",
        ],
    )

    assert run.returncode == 2
    assert run.stdout == ""
    assert "unknown subcommand" in run.stderr
    _assert_clean_client_boundary(run)


def test_qa_browser_screenshot_missing_harness_reports_product_requirement(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(
        tmp_path,
        [
            "qa",
            "browser",
            "screenshot",
            "https://x.example/route",
            "--output",
            str(tmp_path / "shot.png"),
        ],
        include_harness=False,
    )

    assert run.returncode == 2
    assert "requires yoke-harness" in run.stderr
    assert run.boundary["caught"] is None
    assert run.boundary["blocked_attempts"] == []
    assert run.boundary["forbidden_loaded"] == []
    assert _repo_pythonpath(run) == [str(CLI_SRC), str(CONTRACTS_SRC)]
