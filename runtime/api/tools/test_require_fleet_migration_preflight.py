"""Receipt-query diagnostics for the hosted release migration gate."""

from __future__ import annotations

import json
import subprocess

from runtime.api.tools import require_fleet_migration_preflight as preflight


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
