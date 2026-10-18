"""Measure a run's recorded start timings; never start or retry a deployment."""

import argparse
import json
import os

from yoke_contracts.timestamps import InvalidInstant, parse_instant


class StartEvidenceError(ValueError):
    """The recorded timings cannot prove a completed start."""


def start_report(stored, *, run_id, baseline_seconds):
    """Measure the start gap from a run's recorded timings."""
    records = []
    for stored_record in stored:
        record = dict(stored_record)
        if record.get("run_id") == run_id:
            if "timestamp" in record:
                try:
                    record["timestamp"] = parse_instant(record["timestamp"])
                except InvalidInstant as exc:
                    raise StartEvidenceError(
                        "start_clock_invalid: a recorded timing supplies an invalid "
                        "instant; inspect `yoke deployment-runs timings "
                        f"{run_id} --json`"
                    ) from exc
            records.append(record)
    starts = [
        r
        for r in records
        if r.get("step") in {"driver_preflight", "pin_read"}
        and r.get("phase") == "start"
    ]
    ends = [
        r
        for r in records
        if r.get("step") == "executing_transition"
        and r.get("phase") == "end"
        and r.get("outcome") == "ok"
    ]
    contexts = [
        r
        for r in records
        if r.get("step") == "execution_context" and r.get("phase") == "end"
    ]
    if not starts or not ends:
        raise StartEvidenceError(
            "start_timing_incomplete: preflight or successful executing transition absent; read `yoke deployment-runs timings RUN-ID` and look for a `Deployment timing record refused` line in the driver capture"
        )
    if len(contexts) != 1:
        raise StartEvidenceError(
            f"start_context_count: expected one context build, observed {len(contexts)}; inspect retries and correct duplicate context construction"
        )
    steps = {}
    for record in records:
        if record.get("phase") == "end":
            key = record["step"]
            steps[key] = steps.get(key, 0) + float(record.get("elapsed_ms", 0))
    if any(record.get("timestamp") is None for record in (*starts, *ends)):
        raise StartEvidenceError(
            "start_clock_invalid: required driver clock is absent; "
            "recover the complete original markers"
        )
    first = min(r["timestamp"] for r in starts)
    last = max(r["timestamp"] for r in ends)
    elapsed = (last - first).total_seconds()
    if elapsed < 0:
        raise StartEvidenceError(
            "start_clock_invalid: driver timestamps run backwards; recover markers from one driver invocation"
        )
    identity = ends[-1]
    if not identity.get("source_sha") or identity.get("member_count") is None:
        raise StartEvidenceError(
            "start_identity_missing: successful transition lacks source/member facts; inspect this driver's context markers"
        )
    required = {
        "pin_read",
        "worktree_retirement",
        "worktree_ensure",
        "child_start",
        "branch_verification",
        "qa_seed",
        "containment_attestation",
        "composition_freeze",
        "executing_stamp",
    }
    missing = sorted(required - steps.keys())
    if missing:
        raise StartEvidenceError(
            f"start_steps_missing: {', '.join(missing)}; a driver scope did not record; read `yoke deployment-runs timings RUN-ID` and the driver capture's refusal lines"
        )
    return {
        "run_id": run_id,
        "source_sha": identity["source_sha"],
        "member_count": identity["member_count"],
        "transport": identity["transport"],
        "baseline_seconds": baseline_seconds,
        "start_gap_seconds": round(elapsed, 3),
        "reduction_seconds": round(baseline_seconds - elapsed, 3),
        "context_builds": len(contexts),
        "step_elapsed_ms": steps,
    }


def recorded_timings(run_id):
    """Read the run's stored timings through the registered read."""
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    response = call_dispatcher(
        function_id="deployment_runs.timings",
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={},
    )
    if not response.success:
        error = response.error
        raise StartEvidenceError(
            "start_timings_unavailable: "
            + (f"{error.code}: {error.message}" if error else "read refused")
            + "; confirm `yoke deployment-runs timings RUN-ID` is served"
        )
    return (response.result or {}).get("records") or []


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=os.environ.get("DEPLOYMENT_RUN_ID"))
    parser.add_argument("--baseline-seconds", type=float, required=True)
    args = parser.parse_args(argv)
    if not args.run_id:
        parser.error("--run-id or DEPLOYMENT_RUN_ID is required")
    try:
        report = start_report(
            recorded_timings(args.run_id),
            run_id=args.run_id,
            baseline_seconds=args.baseline_seconds,
        )
    except (StartEvidenceError, ValueError, KeyError, TypeError) as exc:
        reason = (
            str(exc)
            if isinstance(exc, StartEvidenceError)
            else f"start_timings_invalid: {exc}; inspect "
            f"`yoke deployment-runs timings {args.run_id} --json`"
        )
        print(f"Deployment start evidence refused: {reason}")
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
