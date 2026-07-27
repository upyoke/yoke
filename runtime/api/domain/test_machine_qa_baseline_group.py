from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    OpenFixtureConnection,
    baseline_group_request,
    materialize_installer_campaign,
)
from yoke_core.domain.handlers.test_machine_case import (
    handle_baseline_group_execute,
)
from yoke_core.domain.machine_qa_execution import (
    MachineCaseResult,
)


class _GroupExecution:
    def __init__(self, *, baseline_ok: bool) -> None:
        self.baseline_ok = baseline_ok
        self.baseline = None
        self.active = False
        self.baseline_calls: list[str] = []
        self.execute_calls: list[dict[str, Any]] = []

    def __enter__(self) -> "_GroupExecution":
        assert not self.active
        self.active = True
        return self

    def __exit__(self, *_args) -> None:
        self.active = False

    def reach_baseline(self, name: str) -> SimpleNamespace:
        assert self.active
        self.baseline_calls.append(name)
        self.baseline = SimpleNamespace(
            name=name,
            ok=self.baseline_ok,
            error_code=(None if self.baseline_ok else "baseline_verification_failed"),
        )
        return self.baseline

    def execute(self, **contract: Any) -> MachineCaseResult:
        assert self.active
        self.execute_calls.append(dict(contract))
        if not self.baseline_ok:
            return MachineCaseResult(
                case_outcome="blocked_on_precondition",
                verdict="blocked",
                evidence={"case_started": False},
                error_code="baseline_verification_failed",
            )
        return MachineCaseResult(
            case_outcome="passed",
            verdict="pass",
            evidence={"case_started": True},
        )


def _recording_stub(
    execution: _GroupExecution,
    recorded: list[tuple[int, MachineCaseResult]],
):
    def record(
        _conn: Any,
        *,
        case: dict[str, Any],
        result: MachineCaseResult,
        duration_ms: int,
    ) -> dict[str, Any]:
        assert execution.active
        assert duration_ms >= 0
        requirement_id = int(case["requirement_id"])
        recorded.append((requirement_id, result))
        verdict = "pass" if result.verdict == "pass" else "inconclusive"
        return {
            "requirement_id": requirement_id,
            "executor_id": "host_control",
            "verdict": verdict,
            "case_outcome": result.case_outcome,
            "run_id": requirement_id + 1000,
            "evidence_count": 1,
            "capture_degraded_reason": result.capture_degraded_reason,
            "error_code": result.error_code,
        }

    return record


def test_baseline_group_acquires_once_and_executes_every_dependent_case(
    test_db,
    monkeypatch,
) -> None:
    rows = materialize_installer_campaign(test_db, item_id=4201)
    fresh = [row for row in rows if row["host_baseline"] == "fresh-host"]
    shell = [row for row in rows if row["host_baseline"] == "shell-preconfigured"]
    assert [row["plan_case_key"] for row in fresh] == [
        "path-001",
        "path-002",
        "path-003",
        "path-005",
        "path-006",
        "mac-011",
    ]
    assert [row["plan_case_key"] for row in shell] == [
        "path-004",
        "state-008",
        "mac-007",
        "mac-010",
        "mac-012",
    ]
    assert {row["id"] for row in fresh}.isdisjoint({row["id"] for row in shell})

    execution = _GroupExecution(baseline_ok=True)
    acquisitions: list[dict[str, Any]] = []
    recorded: list[tuple[int, MachineCaseResult]] = []

    def acquire(_conn: Any, **kwargs: Any) -> _GroupExecution:
        acquisitions.append(dict(kwargs))
        return execution

    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda: OpenFixtureConnection(test_db),
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_execution.acquire_machine_qa_lease",
        acquire,
    )
    monkeypatch.setattr(
        "yoke_core.domain.handlers.test_machine_case._record_machine_case_result",
        _recording_stub(execution, recorded),
    )

    outcome = handle_baseline_group_execute(baseline_group_request(int(fresh[0]["id"])))

    assert outcome.primary_success
    assert len(acquisitions) == 1
    assert acquisitions[0]["project"] == "yoke"
    assert execution.baseline_calls == ["fresh-host"]
    expected_ids = [int(row["id"]) for row in fresh]
    assert outcome.result_payload["requirement_ids"] == expected_ids
    assert [row[0] for row in recorded] == expected_ids
    assert len(execution.execute_calls) == len(expected_ids)
    assert outcome.result_payload["baseline_ok"] is True
    assert all(result.case_outcome == "passed" for _, result in recorded)


def test_failed_group_baseline_records_every_case_as_blocked(
    test_db,
    monkeypatch,
) -> None:
    rows = materialize_installer_campaign(test_db, item_id=4202)
    fresh = [row for row in rows if row["host_baseline"] == "fresh-host"]
    execution = _GroupExecution(baseline_ok=False)
    acquisitions = 0
    recorded: list[tuple[int, MachineCaseResult]] = []

    def acquire(_conn: Any, **_kwargs: Any) -> _GroupExecution:
        nonlocal acquisitions
        acquisitions += 1
        return execution

    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda: OpenFixtureConnection(test_db),
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_execution.acquire_machine_qa_lease",
        acquire,
    )
    monkeypatch.setattr(
        "yoke_core.domain.handlers.test_machine_case._record_machine_case_result",
        _recording_stub(execution, recorded),
    )

    outcome = handle_baseline_group_execute(baseline_group_request(int(fresh[0]["id"])))

    assert outcome.primary_success
    assert acquisitions == 1
    assert execution.baseline_calls == ["fresh-host"]
    assert len(execution.execute_calls) == len(fresh)
    assert outcome.result_payload["baseline_ok"] is False
    assert [row[0] for row in recorded] == [int(row["id"]) for row in fresh]
    assert all(
        result.case_outcome == "blocked_on_precondition"
        and result.verdict == "blocked"
        and result.evidence["case_started"] is False
        for _, result in recorded
    )


def test_baseline_group_rejects_client_supplied_membership(
    monkeypatch,
) -> None:
    connect = SimpleNamespace()
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        connect,
    )

    outcome = handle_baseline_group_execute(
        baseline_group_request(
            41,
            payload={
                "host_baseline": "fresh-host",
                "requirement_ids": [41, 99],
            },
        )
    )

    assert not outcome.primary_success
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
