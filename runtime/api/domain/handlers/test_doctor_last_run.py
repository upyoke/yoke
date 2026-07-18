"""Handler coverage for ``doctor.last_run.get`` (disposable Postgres).

Doctor reports persist only inside ``YokeFunctionCalled`` journal
envelopes, so every fixture here writes synthetic journal rows and
asserts the read serves the newest COMPLETE run — honoring the project
filter, ignoring partial pages, and degrading honestly when the
envelope shrink replaced the stored result with a truncation marker.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_core.domain import last_doctor_run_read
from yoke_core.domain.handlers.doctor_last_run import (
    handle_doctor_last_run_get,
)
from yoke_core.domain.json_helper import dumps_compact
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


def _doctor_result(
    *,
    done: bool = True,
    project: str = "yoke",
    results: Optional[list] = None,
) -> Dict[str, Any]:
    checks = results if results is not None else [
        {"hc": "HC-alpha", "name": "alpha", "severity": "PASS", "detail": ""},
        {"hc": "HC-beta", "name": "beta", "severity": "FAIL", "detail": "f"},
    ]
    return {
        "results": checks,
        "scope": "quick",
        "project": project,
        "fail_count": sum(1 for c in checks if c["severity"] == "FAIL"),
        "warn_count": sum(1 for c in checks if c["severity"] == "WARN"),
        "pass_count": sum(1 for c in checks if c["severity"] == "PASS"),
        "done": done,
        "cursor": checks[-1]["hc"] if checks else None,
    }


def _envelope(
    result: Any,
    *,
    function: str = "doctor.run.run",
) -> str:
    return dumps_compact({
        "event_name": "YokeFunctionCalled",
        "context": {"function": function, "result": result},
    })


def _insert_run(
    conn,
    *,
    event_id: str,
    created_at: str,
    result: Any,
    function: str = "doctor.run.run",
    project: str = "yoke",
) -> None:
    insert_event(
        conn,
        event_id=event_id,
        event_name="YokeFunctionCalled",
        envelope=_envelope(result, function=function),
        created_at=created_at,
        project=project,
    )


class TestLastRunSelection:
    def test_newest_complete_run_wins(self, test_db):
        _insert_run(
            test_db, event_id="evt-old", created_at="2026-01-01T00:00:00Z",
            result=_doctor_result(results=[
                {"hc": "HC-old", "name": "old", "severity": "PASS",
                 "detail": ""},
            ]),
        )
        _insert_run(
            test_db, event_id="evt-new", created_at="2026-01-02T00:00:00Z",
            result=_doctor_result(),
        )
        # A newer journal row for a DIFFERENT function id never poses as
        # a doctor run, even though its envelope mentions the id.
        _insert_run(
            test_db, event_id="evt-other", created_at="2026-01-03T00:00:00Z",
            result={"note": "not doctor; mentions doctor.run.run only"},
            function="items.list.run",
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
            "HC-alpha", "HC-beta",
        ]
        assert set(served["results"][0]) == {
            "hc", "name", "severity", "detail",
        }

    def test_partial_pages_are_not_runs(self, test_db):
        _insert_run(
            test_db, event_id="evt-done", created_at="2026-01-01T00:00:00Z",
            result=_doctor_result(),
        )
        _insert_run(
            test_db, event_id="evt-page", created_at="2026-01-02T00:00:00Z",
            result=_doctor_result(done=False),
        )
        outcome = handle_doctor_last_run_get(_request())
        assert outcome.primary_success
        assert outcome.result_payload["ran_at"] == "2026-01-01T00:00:00Z"

    def test_only_partial_pages_means_never_run(self, test_db):
        _insert_run(
            test_db, event_id="evt-page", created_at="2026-01-01T00:00:00Z",
            result=_doctor_result(done=False),
        )
        outcome = handle_doctor_last_run_get(_request())
        assert outcome.primary_success
        assert outcome.result_payload == {"never_run": True}

    def test_never_run_on_an_empty_journal(self, test_db):
        outcome = handle_doctor_last_run_get(_request())
        assert outcome.primary_success
        assert outcome.result_payload == {"never_run": True}

    def test_scan_pages_past_newer_non_matching_rows(self, test_db, monkeypatch):
        monkeypatch.setattr(last_doctor_run_read, "SCAN_BATCH_SIZE", 1)
        _insert_run(
            test_db, event_id="evt-done", created_at="2026-01-01T00:00:00Z",
            result=_doctor_result(),
        )
        for n in (2, 3):
            _insert_run(
                test_db, event_id=f"evt-page-{n}",
                created_at=f"2026-01-0{n}T00:00:00Z",
                result=_doctor_result(done=False),
            )
        outcome = handle_doctor_last_run_get(_request())
        assert outcome.primary_success
        assert outcome.result_payload["ran_at"] == "2026-01-01T00:00:00Z"


class TestProjectFilter:
    def test_project_filter_prefers_the_matching_run(self, test_db):
        _insert_run(
            test_db, event_id="evt-externalwebapp", created_at="2026-01-01T00:00:00Z",
            result=_doctor_result(project="externalwebapp"), project="externalwebapp",
        )
        _insert_run(
            test_db, event_id="evt-yoke", created_at="2026-01-02T00:00:00Z",
            result=_doctor_result(project="yoke"),
        )
        outcome = handle_doctor_last_run_get(_request({"project": "externalwebapp"}))
        assert outcome.primary_success
        served = outcome.result_payload
        assert served["ran_at"] == "2026-01-01T00:00:00Z"
        assert served["project"] == "externalwebapp"

    def test_mismatched_run_never_poses_as_the_project(self, test_db):
        _insert_run(
            test_db, event_id="evt-yoke", created_at="2026-01-01T00:00:00Z",
            result=_doctor_result(project="yoke"),
        )
        # The externalwebapp project exists (this row registers it) but its only
        # journal trace is a partial page — never a served run.
        _insert_run(
            test_db, event_id="evt-externalwebapp-page",
            created_at="2026-01-02T00:00:00Z",
            result=_doctor_result(project="externalwebapp", done=False), project="externalwebapp",
        )
        outcome = handle_doctor_last_run_get(_request({"project": "externalwebapp"}))
        assert outcome.primary_success
        assert outcome.result_payload == {"never_run": True}

    def test_unknown_project_is_a_typed_error(self, test_db):
        outcome = handle_doctor_last_run_get(
            _request({"project": "no-such-project"})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "not_found"

    def test_non_string_project_is_rejected(self):
        outcome = handle_doctor_last_run_get(_request({"project": 7}))
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"


class TestTruncatedEnvelope:
    def test_shrunk_result_serves_the_degraded_state(self, test_db):
        _insert_run(
            test_db, event_id="evt-shrunk", created_at="2026-01-02T00:00:00Z",
            result={"_truncated_value": True, "_bytes": 123456},
        )
        outcome = handle_doctor_last_run_get(_request())
        assert outcome.primary_success
        served = outcome.result_payload
        assert served["truncated"] is True
        assert served["never_run"] is False
        assert served["ran_at"] == "2026-01-02T00:00:00Z"
        assert served["results"] == []
        # Counts inside a wholesale-replaced result are unrecoverable —
        # served as None, never invented zeros.
        assert served["pass_count"] is None
        assert served["warn_count"] is None
        assert served["fail_count"] is None
        assert served["total"] is None

    def test_shrunk_result_cannot_satisfy_a_project_filter(self, test_db):
        # Register the project so resolution succeeds; its only doctor
        # trace is project-unreadable, so the filter falls to never_run.
        insert_event(
            test_db, event_id="evt-any", event_name="SomethingElse",
            project="externalwebapp",
        )
        _insert_run(
            test_db, event_id="evt-shrunk", created_at="2026-01-02T00:00:00Z",
            result={"_truncated_value": True, "_bytes": 99},
        )
        outcome = handle_doctor_last_run_get(_request({"project": "externalwebapp"}))
        assert outcome.primary_success
        assert outcome.result_payload == {"never_run": True}


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
