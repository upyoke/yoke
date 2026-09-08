"""Evidence persistence for executed machine-QA cases."""

from __future__ import annotations

import json
from pathlib import Path
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
        parse_handle,
        serialize_handle,
    )
    from yoke_core.domain.qa_artifact_storage import (
        store_artifact_bytes,
        store_artifact_file,
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
        evidence_handle = store_artifact_bytes(
            conn,
            requirement_id=int(case["requirement_id"]),
            run_id=run_id,
            filename="machine-evidence.json",
            content=raw_result.encode("utf-8"),
            content_type="application/json",
        )
        if local_artifact_created is not None and evidence_handle["backend"] == "local":
            local_artifact_created(Path(str(evidence_handle["path"])))
        metadata = {
            "case_key": str(case["case_key"]),
            "host_baseline": case.get("host_baseline"),
            "machine": result.evidence.get("machine"),
        }
        add_artifact(
            "machine_evidence",
            "application/json",
            evidence_handle,
            metadata,
        )
        for key, raw_handle in _artifact_handles(result.evidence):
            handle = parse_handle(raw_handle)
            if handle["backend"] == "local":
                source = Path(str(handle["path"])).expanduser()
                if not source.is_file():
                    raise ValueError(
                        f"machine QA capture {key!r} was not transferred: no "
                        f"bytes at {source} on this machine. The submitting "
                        "host sends capture bytes alongside its result; "
                        "recording the handle alone would present evidence "
                        "this control plane can never read. Re-run the case "
                        "so the capture is submitted with its bytes."
                    )
                handle = store_artifact_file(
                    conn,
                    requirement_id=int(case["requirement_id"]),
                    run_id=run_id,
                    path=source,
                    filename=f"{key}.png",
                    content_type="image/png",
                )
                if local_artifact_created is not None and handle["backend"] == "local":
                    local_artifact_created(Path(str(handle["path"])))
                source.unlink(missing_ok=True)
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
