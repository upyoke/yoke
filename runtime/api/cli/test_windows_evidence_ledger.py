"""Every CLI route needs an expected Windows row; only receipts prove it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.commands.command_tree import command_routes
from yoke_cli.windows_evidence_ledger import MODES, expected_rows, load_rows, validate_rows
from yoke_cli.windows_evidence_report import report
from yoke_contracts.windows_ledger_receipt import tag_receipt
from runtime.api.tools.windows_evidence import main

ROOT = Path(__file__).resolve().parents[3]


def test_every_command_surface_and_mode_has_checked_in_windows_expectation():
    rows = load_rows(ROOT)
    validate_rows(rows, expected_rows(ROOT))
    identities = {(row["operation"], row["surface"], row["mode"]) for row in rows}
    for route in command_routes():
        for mode in MODES:
            assert ("yoke " + " ".join(route), "cli", mode) in identities
    assert any(row["operation"].startswith("hook ") for row in rows)
    assert any(row["operation"].startswith("desktop ") for row in rows)
    with pytest.raises(ValueError, match="windows_ledger_drift"):
        validate_rows(rows[1:], expected_rows(ROOT))


def row(expectation="must-pass", reason=""):
    return {"row_id": "windows-test", "expectation": expectation, "reason": reason}


def receipt(*, identity=1, outcome="passed", verdict="pass", **facts):
    native = dict(os="windows", edition="Windows 11 Pro", build="26100",
                  harness_version={"codex": "1.0"}, yoke_release="1.2.3",
                  observed_outcome=outcome, row_ids=["windows-test"])
    native.update(facts)
    return dict(id=identity, completed_at="2026-11-16T12:00:00Z", verdict=verdict,
                raw_result=json.dumps({"evidence": {"windows_ledger": native}}))


def state(rows, receipts):
    return report(rows, receipts, yoke_release="1.2.3")[0]["state"]


@pytest.mark.parametrize("facts", [dict(os="wsl"), dict(os="linux"), dict(build=None),
                                    dict(edition=None), dict(harness_version={}),
                                    dict(yoke_release="older")])
def test_non_native_or_incomplete_or_different_release_is_unproven(facts):
    assert state([row()], [receipt(**facts)]) == "unproven"


def test_missing_receipt_and_declared_na_never_imply_proof():
    assert state([row()], []) == "unproven"
    assert state([row("not-applicable", "no desktop create")], []) == "unproven"


def test_latest_failure_supersedes_previous_pass():
    receipts = [receipt(identity=2, verdict="fail", outcome="failed"), receipt(identity=1)]
    assert state([row()], receipts) == "failed"
    assert state([row()], [receipt()]) == "proven"
    assert state([row()], [receipt(identity=1), receipt(identity=2, build=None)]) == "unproven"


def test_expected_refusal_requires_exact_reason_and_never_proves_must_pass():
    refused = receipt(outcome="refused", reason="native_server_requires_wsl")
    assert state([row("expected-refusal", "native_server_requires_wsl")], [refused]) == "refused"
    assert state([row()], [refused]) == "failed"
    assert state([row("expected-refusal", "different")], [refused]) == "failed"


def test_upstream_limitation_stays_visible_as_failed_operation():
    assert state([row("upstream-limitation", "Cursor defect")], [
        receipt(outcome="upstream_limitation", verdict="fail")
    ]) == "upstream-limitation"


def test_tagging_uses_execution_bound_case_ids_and_native_connection_facts():
    tagged = tag_receipt({"windows_ledger_row_ids": ["windows-test"]},
                         {"connection": {"os": "windows", "build": "26100"},
                          "windows_ledger": {"row_ids": ["windows-forged"], "observed_outcome": "passed"}})
    assert tagged["windows_ledger"]["row_ids"] == ["windows-test"]
    assert tagged["windows_ledger"]["build"] == "26100"
    assert tagged["windows_ledger"]["yoke_release"] is None
    with pytest.raises(ValueError, match="windows_ledger_tags_invalid"):
        tag_receipt({"windows_ledger_row_ids": "windows-test"}, {})


def test_read_only_report_command_retains_unproven_rows(tmp_path, capsys):
    path = tmp_path / "receipts.json"
    path.write_text("[]", encoding="utf-8")
    assert main(["report", "--target-root", str(ROOT), "--receipts", str(path),
                 "--yoke-release", "candidate"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows
    assert all(row["state"] == "unproven" and row["qa_run_id"] is None for row in rows)
