"""Receipt-query diagnostics for the hosted release migration gate."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

from runtime.api.tools import require_fleet_migration_preflight as preflight
from runtime.api.tools import yoke_migration_fleet


def test_query_failure_preserves_advisory_stderr_and_api_error_stdout(
    monkeypatch,
) -> None:
    result = subprocess.CompletedProcess(
        args=["yoke", "events", "query"],
        returncode=1,
        stdout=json.dumps({"success": False, "error": {"code": "permission_denied"}}),
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


def test_applied_migration_query_reads_typed_digest_rows(monkeypatch) -> None:
    expected = [["0015_entry", "a" * 64]]
    result = subprocess.CompletedProcess(
        args=["yoke", "db", "read"],
        returncode=0,
        stdout=json.dumps(
            {
                "success": True,
                "result": {
                    "columns": ["migration_name", "content_sha256"],
                    "rows": expected,
                    "truncated": False,
                },
            }
        ),
        stderr="this checkout is ahead of the server's build",
    )
    monkeypatch.setattr(preflight.subprocess, "run", lambda *args, **kwargs: result)

    rows, unreadable = preflight._query_applied_migrations()

    assert rows == [("0015_entry", "a" * 64)]
    assert unreadable == ""


def test_applied_migration_query_refuses_truncated_evidence(monkeypatch) -> None:
    result = subprocess.CompletedProcess(
        args=["yoke", "db", "read"],
        returncode=0,
        stdout=json.dumps(
            {
                "success": True,
                "result": {
                    "columns": ["migration_name", "content_sha256"],
                    "rows": [],
                    "truncated": True,
                },
            }
        ),
        stderr="",
    )
    monkeypatch.setattr(preflight.subprocess, "run", lambda *args, **kwargs: result)

    rows, unreadable = preflight._query_applied_migrations()

    assert rows == []
    assert unreadable == "applied migration query was truncated"


def test_refusal_recipe_records_on_the_gate_connection(monkeypatch, capsys) -> None:
    monkeypatch.setenv("YOKE_ENV", "prod")
    monkeypatch.setattr(
        yoke_migration_fleet,
        "history_names",
        lambda: ("0005_x",),
    )
    monkeypatch.setattr(preflight, "_query_receipts", lambda *_args: ([], ""))
    monkeypatch.setattr(preflight, "_query_applied_migrations", lambda: ([], ""))

    assert preflight.main(["prod", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "yoke watch preflight -- prod-db-admin" in refusal
    assert "--engine-wheel <yoke_core-wheel-from-yoke-build-artifacts>" in refusal
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
    monkeypatch.setattr(preflight, "_query_applied_migrations", lambda: ([], ""))

    assert preflight.main(["prod-db-admin", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "yoke watch preflight -- prod-db-admin" in refusal
    assert "--engine-wheel <yoke_core-wheel-from-yoke-build-artifacts>" in refusal
    assert "--receipt-env <control-plane-connection>" in refusal


def test_receipt_coverage_is_read_for_the_registered_environment_name(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        yoke_migration_fleet,
        "history_names",
        lambda: ("0005_x",),
    )
    monkeypatch.setattr(
        preflight,
        "_query_receipts",
        lambda *_args: (
            [{"envelope": {"context": {"environment": "prod", "entries": ["0005_x"]}}}],
            "",
        ),
    )
    monkeypatch.setattr(preflight, "_query_applied_migrations", lambda: ([], ""))

    assert preflight.main(["prod", "abc123"]) == 0

    report = capsys.readouterr().out
    assert "target environment: prod" in report
    assert "covered by a passing fleet preflight: 1 of 1" in report


def test_refusal_names_every_environment_missing_a_receipt(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        yoke_migration_fleet, "history_names", lambda: ("0005_x",)
    )
    monkeypatch.setattr(preflight, "_query_receipts", lambda *_args: ([], ""))
    monkeypatch.setattr(preflight, "_query_applied_migrations", lambda: ([], ""))

    assert preflight.main(["prod", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "per environment" in refusal
    assert "stage-db-admin" in refusal
    assert "prod-db-admin" in refusal
    assert "yoke-build-artifacts" in refusal
    assert "commit abc123" in refusal
    assert "gh run" not in refusal


def test_a_receipt_for_only_one_environment_does_not_cover_the_other(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        yoke_migration_fleet, "history_names", lambda: ("0005_x",)
    )
    monkeypatch.setattr(
        preflight,
        "_query_receipts",
        lambda *_args: (
            [{"envelope": {"context": {"environment": "prod", "entries": ["0005_x"]}}}],
            "",
        ),
    )
    monkeypatch.setattr(preflight, "_query_applied_migrations", lambda: ([], ""))

    assert preflight.main(["stage", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "stage" in refusal
    assert "0005_x" in refusal
    assert "per environment" in refusal
    assert "prod" in refusal
    assert "does not transfer" in refusal
    assert "yoke watch preflight -- stage-db-admin" in refusal
    assert "yoke-build-artifacts" in refusal


def test_content_mismatch_refuses_before_receipt_query(monkeypatch, capsys) -> None:
    entry = SimpleNamespace(name="0015_entry", content_sha256="b" * 64)
    monkeypatch.setattr(
        yoke_migration_fleet, "history_names", lambda: (entry.name,)
    )
    monkeypatch.setattr(
        yoke_migration_fleet, "history_entries", lambda: (entry,)
    )
    monkeypatch.setattr(
        preflight,
        "_query_applied_migrations",
        lambda: ([(entry.name, "a" * 64)], ""),
    )

    def _receipt_query_must_not_run(*_args):
        raise AssertionError("receipt query ran after content mismatch")

    monkeypatch.setattr(preflight, "_query_receipts", _receipt_query_must_not_run)

    assert preflight.main(["prod", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "release refused before tag" in refusal
    assert entry.name in refusal
    assert f"ledger={'a' * 64}" in refusal
    assert f"packaged={'b' * 64}" in refusal


def test_unreadable_ledger_refuses_before_receipt_query(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        yoke_migration_fleet, "history_names", lambda: ("0015_entry",)
    )
    monkeypatch.setattr(
        preflight,
        "_query_applied_migrations",
        lambda: ([], "permission denied"),
    )

    def _receipt_query_must_not_run(*_args):
        raise AssertionError("receipt query ran after unreadable ledger")

    monkeypatch.setattr(preflight, "_query_receipts", _receipt_query_must_not_run)

    assert preflight.main(["prod", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "release refused before tag" in refusal
    assert "permission denied" in refusal
