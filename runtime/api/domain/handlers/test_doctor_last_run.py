"""Handler coverage for ``doctor.last_run.get`` (disposable Postgres).

Receipts live in ``doctor_runs``. The events journal is never a source.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain import last_doctor_run_read
from yoke_core.domain.handlers.doctor_last_run import (
    handle_doctor_last_run_get,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.conftest import insert_event


def _request(payload: Optional[Dict[str, Any]] = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="doctor.last_run.get",
        actor=ActorContext(actor_id="op", session_id="s-caller"),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def _doctor_payload(
    *,
    project: str = "yoke",
    ran_at: str,
    results: Optional[list] = None,
) -> Dict[str, Any]:
    checks = (
        results
        if results is not None
        else [
            {"hc": "HC-alpha", "name": "alpha", "severity": "PASS", "detail": ""},
            {"hc": "HC-beta", "name": "beta", "severity": "FAIL", "detail": "f"},
        ]
    )
    return {
        "results": checks,
        "scope": "quick",
        "project": project,
        "runtime": "local",
        "ran_at": ran_at,
        "fail_count": sum(1 for c in checks if c["severity"] == "FAIL"),
        "warn_count": sum(1 for c in checks if c["severity"] == "WARN"),
        "pass_count": sum(1 for c in checks if c["severity"] == "PASS"),
        "na_count": sum(1 for c in checks if c["severity"] == "N/A"),
    }


class TestLastRunSelection:
    def test_newest_complete_run_wins(self, test_db):
        last_doctor_run_read.record_doctor_run(
            test_db,
            _doctor_payload(
                ran_at="2026-01-01T00:00:00Z",
                results=[
                    {
                        "hc": "HC-old",
                        "name": "old",
                        "severity": "PASS",
                        "detail": "",
                    }
                ],
            ),
        )
        last_doctor_run_read.record_doctor_run(
            test_db,
            _doctor_payload(ran_at="2026-01-02T00:00:00Z"),
        )
        insert_event(
            test_db,
            event_id="evt-other",
            event_name="YokeFunctionCalled",
            created_at="2026-01-03T00:00:00Z",
        )
        outcome = handle_doctor_last_run_get(_request())
        assert outcome.primary_success
        served = outcome.result_payload
        assert served["never_run"] is False
        assert served["ran_at"] == "2026-01-02T00:00:00Z"
        assert served["scope"] == "quick"
        assert served["project"] == "yoke"
        assert served["pass_count"] == 1
        assert served["fail_count"] == 1
        assert served["warn_count"] == 0
        assert served["total"] == 2
        assert served["truncated"] is False
        assert [c["hc"] for c in served["results"]] == [
            "HC-alpha",
            "HC-beta",
        ]
        assert set(served["results"][0]) == {
            "hc",
            "name",
            "severity",
            "detail",
        }

    def test_never_run_on_an_empty_table(self, test_db):
        outcome = handle_doctor_last_run_get(_request())
        assert outcome.primary_success
        assert outcome.result_payload == {"never_run": True}

    def test_journal_rows_are_not_receipts(self, test_db):
        insert_event(
            test_db,
            event_id="evt-journal",
            event_name="YokeFunctionCalled",
            created_at="2026-01-02T00:00:00Z",
        )
        outcome = handle_doctor_last_run_get(_request())
        assert outcome.primary_success
        assert outcome.result_payload == {"never_run": True}


class TestProjectFilter:
    def test_project_filter_prefers_the_matching_run(self, test_db):
        last_doctor_run_read.record_doctor_run(
            test_db,
            _doctor_payload(
                project="externalwebapp",
                ran_at="2026-01-01T00:00:00Z",
            ),
        )
        last_doctor_run_read.record_doctor_run(
            test_db,
            _doctor_payload(ran_at="2026-01-02T00:00:00Z"),
        )
        outcome = handle_doctor_last_run_get(
            _request({"project": "externalwebapp"}),
        )
        assert outcome.primary_success
        served = outcome.result_payload
        assert served["ran_at"] == "2026-01-01T00:00:00Z"
        assert served["project"] == "externalwebapp"

    def test_mismatched_run_never_poses_as_the_project(self, test_db):
        last_doctor_run_read.record_doctor_run(
            test_db,
            _doctor_payload(ran_at="2026-01-01T00:00:00Z"),
        )
        outcome = handle_doctor_last_run_get(
            _request({"project": "externalwebapp"}),
        )
        assert outcome.primary_success
        assert outcome.result_payload == {"never_run": True}

    def test_unknown_project_is_a_typed_error(self, test_db):
        outcome = handle_doctor_last_run_get(_request({"project": "no-such-project"}))
        assert not outcome.primary_success
        assert outcome.error.code == "not_found"

    def test_non_string_project_is_rejected(self):
        outcome = handle_doctor_last_run_get(_request({"project": 7}))
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"


class TestReceiptPersist:
    def test_receipt_payload_is_readable(self, test_db):
        outcome = last_doctor_run_read.record_receipt_from_payload(
            _doctor_payload(ran_at="2026-04-01T12:00:00Z"),
        )
        assert outcome.primary_success
        served = handle_doctor_last_run_get(_request()).result_payload
        assert served["ran_at"] == "2026-04-01T12:00:00Z"
        assert served["fail_count"] == 1

    def test_run_handler_receipt_skips_scope(self, test_db):
        from yoke_core.domain.handlers import reads_misc

        outcome = reads_misc.handle_doctor_run(
            _request(
                {
                    "receipt": _doctor_payload(ran_at="2026-04-02T00:00:00Z"),
                }
            )
        )
        assert outcome.primary_success
        served = handle_doctor_last_run_get(_request()).result_payload
        assert served["ran_at"] == "2026-04-02T00:00:00Z"


class TestUiExposure:
    def test_read_is_on_the_ui_allowlist(self):
        from yoke_core.ui import server as ui_server

        assert "doctor.last_run.get" in ui_server.UI_READ_FUNCTION_ALLOWLIST

    def test_registered_as_a_claimless_global_read(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.yoke_function_registry import lookup

        register_all_handlers()
        entry = lookup("doctor.last_run.get")
        assert entry is not None
        assert list(entry.side_effects) == []
        assert entry.claim_required_kind is None
        assert list(entry.target_kinds) == ["global"]
