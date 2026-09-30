"""Record a Command case's evidence and settle the verdict it decided.

Two writes make one run: the capture bytes become an artifact, and the run
row is completed with the verdict. They fail independently, and the order
matters — by the time the upload runs the verdict is already earned, so a
failed upload must not leave the run unsettled. That would turn one
recoverable problem into two: a decided verdict every latest-run projection
reads as still running, and a capture nobody was told how to reattach.

So the verdict is always recorded, and the upload failure is reported on its
own with the one command that attaches the staged evidence. The two failure
shapes stay apart because they need different recoveries: an unattached
artifact needs one command, and a verdict that could not be settled either
needs two.
"""

from __future__ import annotations

import base64
import json
import shlex
from typing import Callable, Optional

from yoke_contracts.api.function_call import ActorContext

from yoke_core.domain.refusal_recovery import compose_refusal


def _artifact_recovery(requirement_id: int, run_id: int, evidence_path: str) -> str:
    return (
        "attach the staged evidence to this same run with `yoke qa artifact add "
        f"--requirement-id {requirement_id} --run-id {run_id} --artifact-type "
        f"command_output --content-type text/plain --content-file {evidence_path}`"
    )


def _upload_failure_refusal(
    complete: Callable[[], None],
    *,
    run_id: int,
    requirement_id: int,
    verdict: str,
    output_path: str,
    evidence_path: str,
    upload_error: object,
) -> str:
    """Settle the decided run, then compose what is still outstanding."""
    evaluated = (
        f"QA run #{run_id} decided {verdict!r} and its command evidence upload "
        f"failed: {upload_error}. The evidence is staged at {evidence_path} "
        f"(the capture itself stays at {output_path}, which a session holding "
        "a lane claim is not allowed to read)"
    )
    try:
        complete()
    except Exception as settle_error:
        return compose_refusal(
            f"QA run #{run_id} recorded neither its evidence nor its verdict",
            evaluated=(
                f"{evaluated}; completing the run then failed too: {settle_error}"
            ),
            recovery=(
                _artifact_recovery(requirement_id, run_id, evidence_path)
                + ", then settle the verdict with `yoke qa run complete "
                f"--requirement-id {requirement_id} --run-id {run_id} "
                f"--verdict {verdict}`"
            ),
        )
    return compose_refusal(
        f"QA run #{run_id} recorded verdict {verdict!r} but not its command evidence",
        evaluated=f"{evaluated}; the run itself is completed with that verdict",
        recovery=(
            _artifact_recovery(requirement_id, run_id, evidence_path)
            + ". The verdict needs no second write"
        ),
    )


def record_command_run(
    case: dict,
    *,
    performed_by: str,
    raw_result: str,
    duration_ms: int,
    verdict: str,
    output: str,
    filename: str,
    metadata: dict,
    actor: Optional[ActorContext] = None,
) -> tuple[int, int]:
    """Upload command evidence bytes, then settle their durable run."""
    from yoke_core.domain.qa_artifacts import (
        artifact_file_path,
        case_artifact_subject,
        stage_recovery_copy,
    )
    from yoke_core.domain.qa_case_execution import QaCaseExecutionError, recording_leg
    from yoke_core.domain.qa_requirement_pass_currency import (
        stamp_executed_method_config,
    )

    raw_result = stamp_executed_method_config(
        raw_result,
        case.get("method_config"),
        execution_target_digest=case.get("execution_target_digest"),
    )
    call_qa = recording_leg(case, actor=actor)
    run = call_qa(
        "qa.run.add",
        {
            "performed_by": performed_by,
            "raw_result": raw_result,
            "duration_ms": duration_ms,
        },
    )
    run_id = int(run["qa_run_id"])
    requirement_id = int(case["requirement_id"])
    output_path = artifact_file_path(
        str(case["project"]),
        case_artifact_subject(case),
        run_id,
        filename,
    )
    output_bytes = output.encode("utf-8")
    output_path.write_bytes(output_bytes)

    def complete() -> None:
        call_qa(
            "qa.run.complete",
            {
                "run_id": run_id,
                "verdict": verdict,
                "raw_result": raw_result,
                "duration_ms": duration_ms,
            },
        )

    try:
        artifact = call_qa(
            "qa.artifact.add",
            {
                "run_id": run_id,
                "artifact_type": "command_output",
                "content_type": "text/plain",
                "content_base64": base64.b64encode(output_bytes).decode("ascii"),
                "filename": filename,
                "metadata": json.dumps(metadata, sort_keys=True),
            },
        )
    except QaCaseExecutionError as exc:
        raise QaCaseExecutionError(
            _upload_failure_refusal(
                complete,
                run_id=run_id,
                requirement_id=requirement_id,
                verdict=verdict,
                output_path=str(output_path),
                evidence_path=shlex.quote(
                    str(stage_recovery_copy(output_bytes, filename))
                ),
                upload_error=exc,
            )
        ) from exc
    complete()
    return run_id, int(artifact["qa_artifact_id"])


__all__ = ["record_command_run"]
