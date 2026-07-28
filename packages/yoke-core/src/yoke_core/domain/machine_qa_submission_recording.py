"""Server validation and persistence for submitted Machine QA case results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

from yoke_core.domain import db_backend
from yoke_core.domain.handlers.test_machine_case_evidence import (
    record_machine_case_result,
)
from yoke_core.domain.machine_qa_execution import MachineCaseResult
from yoke_core.domain.machine_qa_execution_protocol import (
    HOST_CONTROL_SUBMISSION_RECEIPT_KEY,
    host_control_submission_receipt,
    host_control_submission_receipt_matches,
)
from yoke_core.domain.machine_qa_submission_artifacts import (
    MachineQaSubmissionArtifact,
    ensure_secret_free_result,
    restore_submission_artifacts,
)


class MachineCaseSubmissionResult(BaseModel):
    """One secret-free local result accepted by the hosted authority."""

    model_config = ConfigDict(extra="forbid")

    requirement_id: int = Field(ge=1)
    case_outcome: Literal[
        "passed",
        "failed",
        "needs_review",
        "blocked_on_precondition",
    ]
    verdict: Literal["pass", "fail", "pending", "blocked"]
    evidence: dict[str, Any]
    capture_degraded_reason: str | None = None
    error_code: str | None = None
    duration_ms: int = Field(ge=0)
    artifacts: list[MachineQaSubmissionArtifact] = Field(default_factory=list)


_OUTCOME_VERDICTS = {
    "passed": "pass",
    "failed": "fail",
    "needs_review": "pending",
    "blocked_on_precondition": "blocked",
}


class MachineQaArtifactRollback:
    """Remove only this submission's canonical files until DB commit."""

    def __init__(self) -> None:
        self._paths: list[Path] = []
        self._active = True

    def track(self, path: Path) -> None:
        """Arm a not-yet-written canonical path for rollback cleanup."""
        if not self._active:
            raise RuntimeError("artifact rollback is already finalized")
        candidate = Path(path)
        if candidate in self._paths:
            return
        if candidate.exists():
            raise ValueError(f"Machine QA artifact path already exists: {candidate}")
        self._paths.append(candidate)

    def preserve(self) -> None:
        """Disarm cleanup after the database transaction commits."""
        self._active = False
        self._paths.clear()

    def rollback(self) -> None:
        """Delete tracked files and their now-empty run directories."""
        if not self._active:
            return
        self._active = False
        paths = tuple(reversed(self._paths))
        self._paths.clear()
        errors: list[OSError] = []
        parents = {path.parent for path in paths}
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                errors.append(exc)
        for parent in sorted(parents, key=lambda path: len(path.parts), reverse=True):
            try:
                parent.rmdir()
            except OSError:
                pass
        if errors:
            raise OSError(
                "Machine QA artifact rollback could not remove every file"
            ) from errors[0]


def rollback_machine_submission(
    conn: Any,
    artifacts: MachineQaArtifactRollback,
) -> None:
    """Roll back database state and its submission-scoped local files."""
    try:
        conn.rollback()
    finally:
        artifacts.rollback()


def validate_case_submission(
    case: dict[str, Any],
    result: MachineCaseSubmissionResult,
    *,
    resource_name: str,
) -> None:
    """Refuse a result that does not match its server-issued case."""
    if result.requirement_id != int(case["requirement_id"]):
        raise ValueError("Machine QA result targets the wrong requirement")
    if result.verdict != _OUTCOME_VERDICTS[result.case_outcome]:
        raise ValueError("Machine QA outcome and verdict do not agree")
    if result.case_outcome in {"failed", "blocked_on_precondition"}:
        if not str(result.error_code or "").strip():
            raise ValueError("failed Machine QA result requires an error code")
    elif result.error_code is not None:
        raise ValueError("successful Machine QA result cannot name an error code")
    evidence = result.evidence
    if evidence.get("executor_id") != "host_control":
        raise ValueError("Machine QA evidence names the wrong executor")
    if evidence.get("machine") != resource_name:
        raise ValueError("Machine QA evidence names the wrong test machine")
    if result.case_outcome == "blocked_on_precondition":
        if evidence.get("case_started") is not False:
            raise ValueError("blocked Machine QA evidence must remain unstarted")
    elif evidence.get("method_id") != str(case["method_id"]):
        raise ValueError("Machine QA evidence names the wrong method")
    if evidence.get("baseline") != case.get("host_baseline"):
        raise ValueError("Machine QA evidence names the wrong host baseline")
    ensure_secret_free_result(result.model_dump(mode="json"))


def record_submitted_case(
    conn: Any,
    *,
    case: dict[str, Any],
    result: MachineCaseSubmissionResult,
    resource_name: str,
    artifact_root: Path,
    lease_id: int,
    contract_digest: str,
    artifact_rollback: MachineQaArtifactRollback,
) -> dict[str, Any]:
    """Restore submitted captures and write canonical run/artifact records."""
    validate_case_submission(case, result, resource_name=resource_name)
    evidence = restore_submission_artifacts(
        result.evidence,
        result.artifacts,
        target_dir=artifact_root,
    )
    evidence[HOST_CONTROL_SUBMISSION_RECEIPT_KEY] = host_control_submission_receipt(
        lease_id, contract_digest
    )
    ensure_secret_free_result(evidence)
    return record_machine_case_result(
        conn,
        case=case,
        result=MachineCaseResult(
            case_outcome=result.case_outcome,
            verdict=result.verdict,
            evidence=evidence,
            capture_degraded_reason=result.capture_degraded_reason,
            error_code=result.error_code,
        ),
        duration_ms=result.duration_ms,
        local_artifact_created=artifact_rollback.track,
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def recorded_case_submission(
    conn: Any,
    *,
    requirement_id: int,
    lease_id: int,
    contract_digest: str,
) -> dict[str, Any] | None:
    """Return the first canonical run recorded for an issued submission."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT id,verdict,case_outcome,capture_degraded_reason,raw_result "
        "FROM qa_runs "
        f"WHERE qa_requirement_id={marker} AND executor_type='host_control' "
        "AND completed_at IS NOT NULL ORDER BY id",
        (int(requirement_id),),
    ).fetchall()
    for row in rows:
        raw_result = _json_object(row["raw_result"])
        evidence = _json_object(raw_result.get("evidence"))
        if not host_control_submission_receipt_matches(
            evidence.get(HOST_CONTROL_SUBMISSION_RECEIPT_KEY),
            lease_id=lease_id,
            contract_digest=contract_digest,
        ):
            continue
        artifact_count = int(
            conn.execute(
                f"SELECT COUNT(*) FROM qa_artifacts WHERE qa_run_id={marker}",
                (int(row["id"]),),
            ).fetchone()[0]
        )
        return {
            "requirement_id": int(requirement_id),
            "executor_id": "host_control",
            "verdict": row["verdict"],
            "case_outcome": row["case_outcome"],
            "run_id": int(row["id"]),
            "evidence_count": artifact_count,
            "capture_degraded_reason": row["capture_degraded_reason"],
            "error_code": raw_result.get("error_code"),
            "lease_context": evidence.get("lease"),
        }
    return None


__all__ = [
    "MachineQaArtifactRollback",
    "MachineCaseSubmissionResult",
    "record_submitted_case",
    "recorded_case_submission",
    "rollback_machine_submission",
    "validate_case_submission",
]
