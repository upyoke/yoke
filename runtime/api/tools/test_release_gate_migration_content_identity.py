"""Packaged migration content against the connected applied ledger.

The release gate asks two independent questions before a tag exists: does
the content this build packages match what the fleet already applied, and
has the fleet rehearsed what it has not. This file owns the first; the
coverage half lives in ``test_require_fleet_migration_preflight``.
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from runtime.api.tools import require_fleet_migration_preflight as preflight
from runtime.api.tools import yoke_migration_fleet


def _history(monkeypatch, *names: str) -> tuple[SimpleNamespace, ...]:
    entries = tuple(
        SimpleNamespace(name=name, content_sha256=(str(index) * 64))
        for index, name in enumerate(names, start=1)
    )
    monkeypatch.setattr(yoke_migration_fleet, "history_entries", lambda: entries)
    return entries


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

    def _coverage_read_must_not_run(**_kwargs):
        raise AssertionError("coverage read ran after content mismatch")

    monkeypatch.setattr(
        "yoke_core.domain.migration_preflight_receipt_store.read_coverage",
        _coverage_read_must_not_run,
    )

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

    def _coverage_read_must_not_run(**_kwargs):
        raise AssertionError("coverage read ran after unavailable verification")

    monkeypatch.setattr(
        "yoke_core.domain.migration_preflight_receipt_store.read_coverage",
        _coverage_read_must_not_run,
    )

    assert preflight.main(["prod", "abc123"]) == 2

    refusal = capsys.readouterr().err
    assert "release verification unavailable before tag" in refusal
    assert "permission_denied" in refusal
    assert "release unsafe" not in refusal
