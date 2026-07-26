"""Registered execution and evidence recording for one Machine QA case."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.test_machine import _failure
from yoke_core.domain.test_machine_capability import TestMachineCapabilityError


class TestMachineCaseExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TestMachineCaseExecuteResponse(BaseModel):
    requirement_id: int
    executor_id: str
    verdict: str
    case_outcome: str
    run_id: int
    evidence_count: int
    capture_degraded_reason: str | None
    error_code: str | None


def _artifact_handles(value: Any) -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(value, dict):
        handle = value.get("artifact_handle")
        if isinstance(handle, dict):
            found.append((str(value.get("key") or "capture"), handle))
        for child in value.values():
            found.extend(_artifact_handles(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_artifact_handles(child))
    return found


def _record_machine_case_result(
    conn: Any,
    *,
    case: dict[str, Any],
    result: Any,
    duration_ms: int,
) -> dict[str, Any]:
    from yoke_core.domain import db_backend, qa_events
    from yoke_core.domain.db_helpers import iso8601_now
    from yoke_core.domain.item_activity import touch_for_qa_requirement
    from yoke_core.domain.qa_artifact_handle import (
        local_handle,
        parse_handle,
        serialize_handle,
    )
    from yoke_core.domain.qa_artifacts import artifact_file_path

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    verdict = {
        "pass": "pass",
        "fail": "fail",
        "pending": "inconclusive",
        "blocked": "inconclusive",
    }[result.verdict]
    now = iso8601_now()
    raw_result = json.dumps(
        {
            "evidence": result.evidence,
            "error_code": result.error_code,
            "capture_degraded_reason": result.capture_degraded_reason,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    row = conn.execute(
        "INSERT INTO qa_runs("
        "qa_requirement_id,executor_type,qa_kind,verdict,case_outcome,"
        "capture_degraded_reason,raw_result,duration_ms,started_at,"
        "completed_at,created_at"
        f") VALUES({', '.join([marker] * 11)}) RETURNING id",
        (
            int(case["requirement_id"]), "host_control", str(case["qa_kind"]),
            verdict, result.case_outcome, result.capture_degraded_reason,
            raw_result, duration_ms, now, now, now,
        ),
    ).fetchone()
    run_id = int(row[0])
    touch_for_qa_requirement(conn, int(case["requirement_id"]))
    recorded: list[int] = []

    def add_artifact(
        artifact_type: str,
        content_type: str,
        handle: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        artifact = conn.execute(
            "INSERT INTO qa_artifacts("
            "qa_run_id,artifact_type,content_type,artifact_handle,metadata,"
            "created_at"
            f") VALUES({', '.join([marker] * 6)}) RETURNING id",
            (
                run_id, artifact_type, content_type,
                serialize_handle(parse_handle(handle)),
                json.dumps(metadata, separators=(",", ":"), sort_keys=True),
                now,
            ),
        ).fetchone()
        recorded.append(int(artifact[0]))

    evidence_path = artifact_file_path(
        str(case["project"]), int(case["item_id"]), run_id,
        "machine-evidence.json",
    )
    evidence_path.write_text(raw_result, encoding="utf-8")
    metadata = {
        "case_key": str(case["case_key"]),
        "host_baseline": case.get("host_baseline"),
        "machine": result.evidence.get("machine"),
    }
    add_artifact(
        "machine_evidence",
        "application/json",
        local_handle(str(evidence_path.resolve()), "application/json"),
        metadata,
    )
    for key, raw_handle in _artifact_handles(result.evidence):
        handle = parse_handle(raw_handle)
        if handle["backend"] == "local":
            source = Path(str(handle["path"])).expanduser()
            if source.is_file():
                target = artifact_file_path(
                    str(case["project"]), int(case["item_id"]), run_id,
                    f"{key}.png",
                )
                shutil.copyfile(source, target)
                source.unlink(missing_ok=True)
                handle = local_handle(str(target.resolve()), "image/png")
        add_artifact(
            "terminal_screenshot", "image/png", handle,
            {**metadata, "checkpoint": key},
        )
    conn.commit()
    qa_events.emit_qa_run_event(
        conn,
        db_path=None,
        event_name="QARunCompleted",
        run_id=run_id,
        requirement_id=int(case["requirement_id"]),
        qa_kind=str(case["qa_kind"]),
        verdict=verdict,
    )
    return {
        "requirement_id": int(case["requirement_id"]),
        "executor_id": "host_control",
        "verdict": verdict,
        "case_outcome": result.case_outcome,
        "run_id": run_id,
        "evidence_count": len(recorded),
        "capture_degraded_reason": result.capture_degraded_reason,
        "error_code": result.error_code,
    }


def handle_case_execute(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        TestMachineCaseExecuteRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _failure("payload_invalid", str(exc))
    requirement_id = request.target.qa_requirement_id
    if request.target.kind != "qa_requirement" or requirement_id is None:
        return _failure(
            "target_invalid",
            "test_machine.case_execute requires target.kind='qa_requirement'",
        )
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.machine_qa_execution import acquire_machine_qa_lease
    from yoke_core.domain.machine_qa_method_contracts import (
        MACHINE_METHODS,
        MachineQaExecutionError,
    )
    from yoke_core.domain.qa_case_execution_context import (
        QaCaseExecutionError,
        get_case_execution_context,
    )

    conn = connect()
    try:
        case = get_case_execution_context(
            conn, requirement_id=int(requirement_id),
        )
        if (
            case["executor_id"] != "host_control"
            or case["method_id"] not in MACHINE_METHODS
        ):
            return _failure(
                "test_machine_case_invalid",
                "the requirement is not a registered Machine QA case",
            )
        started = time.monotonic()
        with acquire_machine_qa_lease(
            conn,
            project=str(case["project"]),
            session_id=request.actor.session_id,
            actor_id=request.actor.actor_id,
        ) as execution:
            if case.get("host_baseline"):
                execution.reach_baseline(str(case["host_baseline"]))
            result = execution.execute(
                method_id=str(case["method_id"]),
                method_config=case["method_config"],
                entry_surface=case.get("entry_surface"),
                required_completion=case.get("required_completion"),
            )
        payload = _record_machine_case_result(
            conn,
            case=case,
            result=result,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except (
        QaCaseExecutionError,
        MachineQaExecutionError,
        TestMachineCapabilityError,
        ValueError,
    ) as exc:
        conn.rollback()
        return _failure("test_machine_case_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=payload)


__all__ = [
    "TestMachineCaseExecuteRequest",
    "TestMachineCaseExecuteResponse",
    "handle_case_execute",
]
