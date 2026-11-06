"""Retain every browser capture's result before completing its run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from yoke_contracts.qa_artifact_read import artifact_read_command
from yoke_core.domain.browser_qa_steps import QaArtifactWriteError


def complete_run_with_evidence(
    run_id: int,
    requirement_id: int,
    *,
    artifact_dir: str,
    verdict: str | None,
    execution_status: str,
    raw_result: str,
    artifacts: list[str],
    artifact_ids: list[int],
    actor: Any = None,
) -> tuple[str, str | None, str]:
    """Record the payload through the existing local or hosted artifact writer."""
    from yoke_core.domain import browser_qa as _bqa

    payload = json.loads(raw_result)
    try:
        evidence_path = Path(artifact_dir) / "run-result.json"
        evidence_path.write_text(raw_result, encoding="utf-8")
        artifact_id = _bqa._record_artifact_file(
            run_id, requirement_id, str(evidence_path), "application/json",
            "evidence", json.dumps({"label": "Browser run result"}), actor=actor,
        )
        artifacts.append(str(evidence_path))
        artifact_ids.append(artifact_id)
        # The retained file cannot reference its own not-yet-issued artifact id.
        payload["artifacts"] = list(artifacts)
        payload["artifact_ids"] = list(artifact_ids)
        payload["artifact_reads"] = [
            artifact_read_command(requirement_id, artifact_id)
            for artifact_id in artifact_ids
        ]
    except (OSError, QaArtifactWriteError) as exc:
        execution_status, verdict = "capture_failed", "fail"
        payload["execution_status"], payload["verdict"] = execution_status, verdict
        payload["errors"] = payload.get("errors", "") + (
            f"run_evidence_write_failed:{exc}. Repair artifact storage or scratch "
            f"write access, then rerun yoke qa case run --requirement-id {requirement_id};"
        )
        _bqa._log(payload["errors"])
    _bqa._complete_run(
        run_id, requirement_id, verdict=verdict, execution_status=execution_status,
        raw_result=json.dumps(payload, sort_keys=True), actor=actor,
    )
    return execution_status, verdict, payload.get("errors", "")
