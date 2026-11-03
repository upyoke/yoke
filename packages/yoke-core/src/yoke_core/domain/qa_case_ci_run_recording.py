"""Keep a CI attempt visible from adoption through evidence settlement."""

from __future__ import annotations

import json
import time

from yoke_core.domain.qa_case_execution import QaCaseExecutionError, recording_leg
from yoke_core.domain.qa_command_run_recording import record_command_run
from yoke_core.domain.qa_requirement_pass_currency import stamp_executed_method_config


def start(case, *, evidence, actor):
    """Start the actual attempt and settle abandoned CI attempts it replaces."""
    call = recording_leg(case, actor=actor)
    history = call(
        "qa.run.list", {"requirement_id": int(case["requirement_id"]), "limit": 500}
    )
    raw = stamp_executed_method_config(
        json.dumps(evidence, sort_keys=True),
        case.get("method_config"),
        execution_target_digest=case.get("execution_target_digest"),
    )
    for prior in history["rows"]:
        if (
            prior.get("performed_by") != "ci_run"
            or prior.get("completed_at") is not None
            or prior.get("verdict") is not None
        ):
            continue
        previous = json.loads(prior.get("raw_result") or "{}")
        previous.update(
            {
                "ci_conclusion": "error",
                "failure_class": "infrastructure_transient",
                "error": "qa_ci_executor_abandoned: replaced by a new attempt",
                "replacement_ci_run_id": evidence["ci_run_id"],
                "recovery": "Continue the replacement CI case to its verdict.",
            }
        )
        call(
            "qa.run.complete",
            {
                "run_id": int(prior["id"]),
                "verdict": "error",
                "raw_result": json.dumps(previous, sort_keys=True),
            },
        )
    run_id = int(
        call(
            "qa.run.add",
            {
                "performed_by": "ci_run",
                "raw_result": raw,
            },
        )["qa_run_id"]
    )
    return run_id


def finish(case, *, run_id, raw_result, duration_ms, verdict, output, actor):
    return record_command_run(
        case,
        run_id=run_id,
        performed_by="ci_run",
        raw_result=raw_result,
        duration_ms=duration_ms,
        verdict=verdict,
        output=output,
        filename="ci-run-output.txt",
        metadata={"case_key": case["case_key"], "verdict": verdict},
        actor=actor,
    )


def fail(
    case,
    *,
    run_id,
    evidence,
    started,
    ci_run_id,
    ci_run_source,
    superseded_ci_run_id,
    error,
    actor,
):
    recovery = (
        "qa_ci_execution_error: repair the named cause, then rerun "
        f"`yoke qa case run --requirement-id {case['requirement_id']}` "
        "to adopt or supersede the CI run."
    )
    raw = json.dumps(
        {
            **evidence,
            "ci_run_id": ci_run_id or None,
            "ci_conclusion": "error",
            "ci_run_source": ci_run_source,
            "superseded_ci_run_id": superseded_ci_run_id or None,
            "failure_class": "infrastructure_transient",
            "error": str(error),
            "recovery": recovery,
        },
        sort_keys=True,
    )
    recorded, _ = finish(
        case,
        run_id=run_id,
        raw_result=raw,
        duration_ms=int((time.monotonic() - started) * 1000),
        verdict="error",
        output=f"{error}\n{recovery}",
        actor=actor,
    )
    if isinstance(error, Exception):
        raise QaCaseExecutionError(
            f"CI execution errored; recorded QA run #{recorded}: {error}. {recovery}"
        ) from error
