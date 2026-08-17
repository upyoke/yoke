"""Evidence persistence for executed machine-QA cases."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any, Callable


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


def record_machine_case_result(
    conn: Any,
    *,
    case: dict[str, Any],
    result: Any,
    duration_ms: int,
    local_artifact_created: Callable[[Path], None] | None = None,
) -> dict[str, Any]:
    """Store the run, durable evidence, and telemetry for one machine case."""
    from yoke_core.domain import db_backend, qa_events
    from yoke_core.domain.db_helpers import iso8601_now
    from yoke_core.domain.item_activity import touch_for_qa_requirement
    from yoke_core.domain.qa_artifact_handle import (
        local_handle,
        parse_handle,
        serialize_handle,
    )
    from yoke_core.domain.qa_artifacts import (
        artifact_file_path,
        case_artifact_subject,
    )

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    verdict = {
        "pass": "pass",
        "fail": "fail",
        "pending": None,
        "blocked": None,
        "waiting": None,
    }[result.verdict]
    waiting = result.case_outcome == "waiting"
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
        "qa_requirement_id,performed_by,qa_kind,verdict,case_outcome,"
        "capture_degraded_reason,raw_result,duration_ms,started_at,"
        "completed_at,created_at"
        f") VALUES({', '.join([marker] * 11)}) RETURNING id",
        (
            int(case["requirement_id"]),
            "host_control",
            str(case["qa_kind"]),
            verdict,
            result.case_outcome,
            result.capture_degraded_reason,
            raw_result,
            duration_ms,
            now,
            None if waiting else now,
            now,
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
                run_id,
                artifact_type,
                content_type,
                serialize_handle(parse_handle(handle)),
                json.dumps(metadata, separators=(",", ":"), sort_keys=True),
                now,
            ),
        ).fetchone()
        recorded.append(int(artifact[0]))

    if not waiting:
        artifact_subject = case_artifact_subject(case)
        evidence_path = artifact_file_path(
            str(case["project"]),
            artifact_subject,
            run_id,
            "machine-evidence.json",
        )
        if local_artifact_created is not None:
            local_artifact_created(evidence_path)
        evidence_path.write_text(raw_result, encoding="utf-8")
        metadata = {
            "case_key": str(case["case_key"]),
            "host_baseline": case.get("host_baseline"),
            "machine": result.evidence.get("machine"),
        }
        add_artifact(
            "machine_evidence",
            "application/json",
            local_handle(
                str(evidence_path.resolve()),
                "application/json",
            ),
            metadata,
        )
        for key, raw_handle in _artifact_handles(result.evidence):
            handle = parse_handle(raw_handle)
            if handle["backend"] == "local":
                source = Path(str(handle["path"])).expanduser()
                if source.is_file():
                    target = artifact_file_path(
                        str(case["project"]),
                        artifact_subject,
                        run_id,
                        f"{key}.png",
                    )
                    if local_artifact_created is not None:
                        local_artifact_created(target)
                    shutil.copyfile(source, target)
                    source.unlink(missing_ok=True)
                    handle = local_handle(
                        str(target.resolve()),
                        "image/png",
                    )
            add_artifact(
                "terminal_screenshot",
                "image/png",
                handle,
                {**metadata, "checkpoint": key},
            )
    conn.commit()
    qa_events.emit_qa_run_event(
        conn,
        db_path=None,
        event_name="QARunStarted" if waiting else "QARunCompleted",
        run_id=run_id,
        requirement_id=int(case["requirement_id"]),
        qa_kind=str(case["qa_kind"]),
        verdict=verdict,
    )
    return {
        "requirement_id": int(case["requirement_id"]),
        "runner_id": "host_control",
        "verdict": verdict,
        "case_outcome": result.case_outcome,
        "run_id": run_id,
        "evidence_count": len(recorded),
        "capture_degraded_reason": result.capture_degraded_reason,
        "error_code": result.error_code,
        "lease_context": result.evidence.get("lease"),
    }


__all__ = ["record_machine_case_result"]
