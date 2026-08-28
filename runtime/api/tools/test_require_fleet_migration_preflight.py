"""Semantic-verifier and receipt diagnostics for the hosted release gate."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from runtime.api.tools import require_fleet_migration_preflight as preflight
from runtime.api.tools import yoke_migration_fleet


@pytest.fixture(autouse=True)
def _history_tests_treat_schema_shape_as_covered(monkeypatch):
    """History-coverage tests are not the schema-shape contract.

    Schema-shape refusal lives in ``test_schema_shape_release_gate``.
    """
    monkeypatch.setattr(
        "yoke_core.domain.migration_preflight_receipt.uncovered_schema_shape",
        lambda *_args, **_kwargs: (),
    )


def _history(monkeypatch, *names: str) -> tuple[SimpleNamespace, ...]:
    entries = tuple(
        SimpleNamespace(name=name, content_sha256=(str(index) * 64))
        for index, name in enumerate(names, start=1)
    )
    monkeypatch.setattr(yoke_migration_fleet, "history_entries", lambda: entries)
    return entries


def _verified(monkeypatch, count: int) -> None:
    monkeypatch.setattr(
        preflight,
        "_verify_applied_migrations",
        lambda _entries: (
            {
                "status": "verified",
                "verified_count": count,
                "mismatched_entries": [],
            },
            "",
        ),
    )


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


def test_content_verifier_submits_typed_digests_without_raw_sql(monkeypatch) -> None:
    calls = []
    verdict = {
        "status": "verified",
        "verified_count": 1,
        "mismatched_entries": [],
    }
    result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({"success": True, "result": verdict}),
        stderr="this checkout is ahead of the server's build",
    )

    def _run(argv, **_kwargs):
        calls.append(argv)
        return result

    monkeypatch.setattr(preflight.subprocess, "run", _run)
    candidate = [{"name": "0015_entry", "content_sha256": "a" * 64}]

    status, unavailable = preflight._verify_applied_migrations(candidate)

    assert status == verdict
    assert unavailable == ""
    assert calls[0][:4] == ["yoke", "migration", "content-identity", "verify"]
    assert "db" not in calls[0]
    assert json.loads(calls[0][5]) == candidate


def test_content_verifier_rejects_a_malformed_semantic_verdict(monkeypatch) -> None:
    result = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({"success": True, "result": {"rows": []}}),
        stderr="",
    )
    monkeypatch.setattr(preflight.subprocess, "run", lambda *args, **kwargs: result)

    status, unavailable = preflight._verify_applied_migrations(
        [{"name": "0015_entry", "content_sha256": "a" * 64}]
    )

    assert status == {}
    assert unavailable == "migration identity verifier returned a malformed verdict"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"success": True, "result": []},
        {
            "success": True,
            "result": {
                "status": "verified",
                "verified_count": 1,
                "mismatched_entries": ["0015_entry"],
            },
        },
    ],
)
def test_content_verifier_types_malformed_envelopes_as_unavailable(
    monkeypatch, payload
) -> None:
    result = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload), stderr=""
    )
    monkeypatch.setattr(preflight.subprocess, "run", lambda *args, **kwargs: result)

    status, unavailable = preflight._verify_applied_migrations(
        [{"name": "0015_entry", "content_sha256": "a" * 64}]
    )

    assert status == {}
    assert "malformed" in unavailable


def test_receipt_query_types_a_malformed_envelope_as_unavailable(monkeypatch) -> None:
    result = subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr="")
    monkeypatch.setattr(preflight.subprocess, "run", lambda *args, **kwargs: result)

    rows, unavailable = preflight._query_receipts("Receipt", "yoke")

    assert rows == []
    assert unavailable == "receipt query returned a malformed envelope"


def test_refusal_recipe_records_on_the_gate_connection(monkeypatch, capsys) -> None:
    monkeypatch.setenv("YOKE_ENV", "prod")
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 0)
    monkeypatch.setattr(preflight, "_query_receipts", lambda *_args: ([], ""))

    assert preflight.main(["prod", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "release unsafe before tag" in refusal
    assert "yoke watch preflight -- prod-db-admin" in refusal
    assert "--engine-wheel <yoke_core-wheel-from-yoke-build-artifacts>" not in refusal
    assert "--record-receipt --product-sha <sha>" in refusal
    assert "--receipt-env prod" in refusal
    assert "source tree" in refusal


def test_refusal_recipe_requires_explicit_connection_without_ambient_env(
    monkeypatch, capsys
) -> None:
    monkeypatch.delenv("YOKE_ENV", raising=False)
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 0)
    monkeypatch.setattr(preflight, "_query_receipts", lambda *_args: ([], ""))

    assert preflight.main(["prod-db-admin", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "yoke watch preflight -- prod-db-admin" in refusal
    assert "--receipt-env <control-plane-connection>" in refusal


def test_receipt_coverage_uses_the_registered_environment_name(
    monkeypatch, capsys
) -> None:
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 1)
    monkeypatch.setattr(
        preflight,
        "_query_receipts",
        lambda *_args: (
            [{"envelope": {"context": {"environment": "prod", "entries": ["0005_x"]}}}],
            "",
        ),
    )

    assert preflight.main(["prod", "abc123"]) == 0

    report = capsys.readouterr().out
    assert "target environment: prod" in report
    assert "covered by a passing fleet preflight: 1 of 1" in report


def test_refusal_names_every_environment_missing_a_receipt(monkeypatch, capsys) -> None:
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 0)
    monkeypatch.setattr(preflight, "_query_receipts", lambda *_args: ([], ""))

    assert preflight.main(["prod", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "release unsafe before tag" in refusal
    assert "per environment" in refusal
    assert "stage-db-admin" in refusal
    assert "prod-db-admin" in refusal
    assert "yoke-build-artifacts" in refusal
    assert "commit abc123" in refusal


def test_one_environment_receipt_does_not_cover_the_other(monkeypatch, capsys) -> None:
    _history(monkeypatch, "0005_x")
    _verified(monkeypatch, 1)
    monkeypatch.setattr(
        preflight,
        "_query_receipts",
        lambda *_args: (
            [{"envelope": {"context": {"environment": "prod", "entries": ["0005_x"]}}}],
            "",
        ),
    )

    assert preflight.main(["stage", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "release unsafe before tag" in refusal
    assert "stage" in refusal
    assert "does not transfer" in refusal
    assert "yoke watch preflight -- stage-db-admin" in refusal


def test_content_mismatch_is_unsafe_and_hides_digest_values(
    monkeypatch, capsys
) -> None:
    entry = _history(monkeypatch, "0015_entry")[0]
    monkeypatch.setattr(
        preflight,
        "_verify_applied_migrations",
        lambda _entries: (
            {
                "status": "mismatch",
                "verified_count": 0,
                "mismatched_entries": [entry.name],
            },
            "",
        ),
    )

    def _receipt_query_must_not_run(*_args):
        raise AssertionError("receipt query ran after content mismatch")

    monkeypatch.setattr(preflight, "_query_receipts", _receipt_query_must_not_run)

    assert preflight.main(["prod", "abc123"]) == 1

    refusal = capsys.readouterr().err
    assert "release unsafe before tag" in refusal
    assert entry.name in refusal
    assert entry.content_sha256 not in refusal


def test_unavailable_identity_verification_is_not_reported_as_unsafe(
    monkeypatch, capsys
) -> None:
    _history(monkeypatch, "0015_entry")
    monkeypatch.setattr(
        preflight,
        "_verify_applied_migrations",
        lambda _entries: ({}, "permission_denied"),
    )

    def _receipt_query_must_not_run(*_args):
        raise AssertionError("receipt query ran after unavailable verification")

    monkeypatch.setattr(preflight, "_query_receipts", _receipt_query_must_not_run)

    assert preflight.main(["prod", "abc123"]) == 2

    refusal = capsys.readouterr().err
    assert "release verification unavailable before tag" in refusal
    assert "permission_denied" in refusal
    assert "release unsafe" not in refusal


def test_unavailable_receipt_query_is_not_reported_as_unsafe(
    monkeypatch, capsys
) -> None:
    _history(monkeypatch, "0015_entry")
    _verified(monkeypatch, 1)
    monkeypatch.setattr(
        preflight,
        "_query_receipts",
        lambda *_args: ([], "transport unavailable"),
    )

    assert preflight.main(["prod", "abc123"]) == 2

    refusal = capsys.readouterr().err
    assert "release verification unavailable before tag" in refusal
    assert "transport unavailable" in refusal
    assert "release unsafe" not in refusal
