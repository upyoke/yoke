"""Receipt-query diagnostics for the hosted release migration gate."""

from __future__ import annotations

import json
import subprocess

from runtime.api.tools import require_fleet_migration_preflight as preflight
from runtime.api.tools import yoke_migration_fleet


def test_query_failure_preserves_advisory_stderr_and_api_error_stdout(monkeypatch) -> None:
    result = subprocess.CompletedProcess(
        args=["yoke", "events", "query"],
        returncode=1,
        stdout=json.dumps(
            {"success": False, "error": {"code": "permission_denied"}}
        ),
        stderr="this checkout is ahead of the server's build",
    )
    monkeypatch.setattr(preflight.subprocess, "run", lambda *args, **kwargs: result)

    rows, unreadable = preflight._query_receipts("ReceiptPassed", "yoke")

    assert rows == []
    assert "stderr: this checkout is ahead of the server's build" in unreadable
    assert 'stdout: {"success": false' in unreadable
    assert "permission_denied" in unreadable


def test_query_success_reads_stdout_despite_advisory_stderr(monkeypatch) -> None:
    expected = [{"event_name": "ReceiptPassed"}]
    result = subprocess.CompletedProcess(
        args=["yoke", "events", "query"],
        returncode=0,
        stdout=json.dumps({"success": True, "result": {"rows": expected}}),
        stderr="this checkout is ahead of the server's build",
    )
    monkeypatch.setattr(preflight.subprocess, "run", lambda *args, **kwargs: result)

    rows, unreadable = preflight._query_receipts("ReceiptPassed", "yoke")

    assert rows == expected
    assert unreadable == ""


def test_refusal_recipe_records_on_the_gate_connection(monkeypatch, capsys) -> None:
    monkeypatch.setenv("YOKE_ENV", "prod")
    monkeypatch.setattr(
        yoke_migration_fleet,
        "history_names",
        lambda: ("0005_x",),
    )
    monkeypatch.setattr(preflight, "_query_receipts", lambda *_args: ([], ""))

    assert preflight.main(["production", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "yoke watch preflight -- prod-db-admin" in refusal
    assert "--receipt-env prod" in refusal


def test_refusal_recipe_requires_an_explicit_connection_without_ambient_env(
    monkeypatch, capsys
) -> None:
    monkeypatch.delenv("YOKE_ENV", raising=False)
    monkeypatch.setattr(
        yoke_migration_fleet,
        "history_names",
        lambda: ("0005_x",),
    )
    monkeypatch.setattr(preflight, "_query_receipts", lambda *_args: ([], ""))

    assert preflight.main(["production", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "yoke watch preflight -- prod-db-admin" in refusal
    assert "--receipt-env <control-plane-connection>" in refusal
