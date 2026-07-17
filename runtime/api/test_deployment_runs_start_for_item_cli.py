"""Regression tests for the ``runs start-for-item`` parser/CLI dispatch.

Exercises the parser surface registered in
``deployment_runs_cli_parser`` and the dispatch case in
``deployment_runs_cli.main`` so the AC-44 invariant holds: the new
command is reachable via the canonical
``python3 -m yoke_core.cli.db_router runs start-for-item ...`` path.

The underlying composer is mocked so the test stays deterministic and
does not require a live deployment service.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from unittest import mock

from yoke_core.domain import deployment_runs_cli
from yoke_core.engines.runs_start_for_item import StartForItemResult


def _capture(monkeypatch):
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out_buf)
    monkeypatch.setattr(sys, "stderr", err_buf)
    return out_buf, err_buf


def test_start_for_item_dispatch_success(monkeypatch):
    out_buf, err_buf = _capture(monkeypatch)
    handle = StartForItemResult(
        ok=True, project="yoke", flow="to-prod", target_env="prod",
        run_id="R-1", validation_message="ok", item_ids=[42],
    )
    with mock.patch.object(
        deployment_runs_cli, "start_for_item", return_value=handle,
    ) as mock_composer:
        rc = deployment_runs_cli.main(["start-for-item", "42"])
    assert rc == 0
    mock_composer.assert_called_once()
    args, kwargs = mock_composer.call_args
    assert args[0] == 42
    payload = json.loads(out_buf.getvalue())
    assert payload["ok"] is True
    assert payload["run_id"] == "R-1"
    assert payload["item_ids"] == [42]


def test_start_for_item_dispatch_failure_writes_to_stderr(monkeypatch):
    out_buf, err_buf = _capture(monkeypatch)
    handle = StartForItemResult(
        ok=False, project="yoke", flow=None, target_env=None,
        run_id=None,
        error="item 42 has no deployment_flow; cannot start deploy run",
        error_phase="resolve-target-env",
        item_ids=[42],
    )
    with mock.patch.object(
        deployment_runs_cli, "start_for_item", return_value=handle,
    ):
        rc = deployment_runs_cli.main(["start-for-item", "42"])
    assert rc == 1
    # Successful payload goes to stdout; failure payload goes to stderr.
    assert out_buf.getvalue() == ""
    payload = json.loads(err_buf.getvalue())
    assert payload["ok"] is False
    assert payload["error_phase"] == "resolve-target-env"
    assert "deployment_flow" in payload["error"]


def test_start_for_item_passes_through_optional_kwargs(monkeypatch):
    _capture(monkeypatch)
    handle = StartForItemResult(
        ok=True, project="buzz", flow="to-staging", target_env="staging",
        run_id="R-2", validation_message="ok", item_ids=[7],
    )
    with mock.patch.object(
        deployment_runs_cli, "start_for_item", return_value=handle,
    ) as mock_composer:
        rc = deployment_runs_cli.main([
            "start-for-item", "7",
            "--project", "buzz",
            "--flow", "to-staging",
            "--target-env", "staging",
            "--release-lineage", "L-99",
            "--project-repo-path", "/workspace/buzz",
            "--created-by", "agent",
        ])
    assert rc == 0
    _, kwargs = mock_composer.call_args
    assert kwargs == {
        "project": "buzz",
        "flow": "to-staging",
        "target_env": "staging",
        "release_lineage": "L-99",
        "project_repo_path": "/workspace/buzz",
        "created_by": "agent",
    }


def test_start_for_item_validation_failure_preserves_run_id_in_payload(monkeypatch):
    _, err_buf = _capture(monkeypatch)
    handle = StartForItemResult(
        ok=False, project="yoke", flow="to-prod", target_env="prod",
        run_id="R-3", validation_message="missing item",
        error="validate-composition failed: missing item",
        error_phase="validate-composition",
        item_ids=[42],
    )
    with mock.patch.object(
        deployment_runs_cli, "start_for_item", return_value=handle,
    ):
        rc = deployment_runs_cli.main(["start-for-item", "42"])
    assert rc == 1
    payload = json.loads(err_buf.getvalue())
    # The failure payload names the run_id so the operator can
    # inspect or clean up via existing `runs` commands.
    assert payload["run_id"] == "R-3"
    assert payload["error_phase"] == "validate-composition"


def test_start_for_item_via_db_router_main(monkeypatch, tmp_path):
    """End-to-end through the canonical db_router CLI with YOK-N input."""
    out_buf, _ = _capture(monkeypatch)
    monkeypatch.delenv("YOKE_DB", raising=False)
    handle = StartForItemResult(
        ok=True, project="yoke", flow="to-prod", target_env="prod",
        run_id="R-9", validation_message="ok", item_ids=[42],
    )
    with mock.patch(
        "yoke_core.domain.yok_n_parser.parse_item_id",
        return_value=42,
    ) as mock_parser, mock.patch(
        "yoke_core.domain.deployment_runs_cli.start_for_item",
        return_value=handle,
    ) as mock_composer:
        from yoke_core.cli import db_router
        rc = db_router.main(["runs", "start-for-item", "YOK-1"])
    assert rc == 0
    mock_parser.assert_called_once_with("YOK-1")
    mock_composer.assert_called_once()
    assert mock_composer.call_args.args[0] == 42
    payload = json.loads(out_buf.getvalue())
    assert payload["run_id"] == "R-9"


def test_deployment_runs_cli_module_main_guard_exposes_help():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_core.domain.deployment_runs_cli",
            "--help",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Deployment-run CRUD" in result.stdout
    assert "create-run" in result.stdout
