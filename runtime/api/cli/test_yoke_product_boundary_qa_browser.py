"""Product-boundary fault injection for ``yoke qa browser``."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.test_yoke_product_boundary_fault_injection import (
    CLI_SRC,
    CONTRACTS_SRC,
    _assert_clean_client_boundary,
    _repo_pythonpath,
    _run_product_cli,
)


def _https_config(token_file: Path) -> dict[str, object]:
    token_file.write_text("tok\n", encoding="utf-8")
    return {
        "schema_version": 1,
        "active_env": "stage",
        "connections": {
            "stage": {
                "transport": "https",
                "api_url": "http://127.0.0.1:9",
                "credential_source": {
                    "kind": "token_file",
                    "path": str(token_file),
                },
            },
        },
    }


def test_qa_browser_help_does_not_import_source_authority(tmp_path: Path) -> None:
    run = _run_product_cli(
        tmp_path,
        ["qa", "browser", "screenshot", "--help"],
    )

    assert run.returncode == 0
    assert "usage: yoke qa browser screenshot" in run.stdout
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_qa_browser_run_uses_https_dispatch_without_core_import(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(
        tmp_path,
        [
            "qa",
            "browser",
            "run",
            "--item",
            "BUZ-1732",
            "--project",
            "buzz",
            "--base-url",
            "http://127.0.0.1:1",
        ],
        config_payload=_https_config(tmp_path / "token.txt"),
    )

    assert run.returncode == 2
    assert json.loads(run.stdout)["note"] == "context_unavailable"
    assert "qa.browser_context.get failed" in run.stderr
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
