"""Measure an existing driver capture; never start or retry a deployment."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path

from yoke_core.domain.deployment_start_timing import PREFIX
from yoke_core.domain.project_scratch_dir import (
    global_scratch_root,
    resolve_active_project,
)


class StartEvidenceError(ValueError):
    """The capture cannot prove a completed start."""


def start_report(text, *, run_id, baseline_seconds):
    records = []
    for line in text.splitlines():
        if line.startswith(PREFIX):
            try:
                record = json.loads(line[len(PREFIX) :])
            except json.JSONDecodeError as exc:
                raise StartEvidenceError(
                    "start_timing_invalid: malformed marker; recover the full raw capture"
                ) from exc
            if record.get("run_id") == run_id:
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
            "start_timing_incomplete: preflight or successful executing transition absent; obtain this run's driver raw capture on its execution machine"
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
    first = min(datetime.fromisoformat(r["timestamp"]) for r in starts)
    last = max(datetime.fromisoformat(r["timestamp"]) for r in ends)
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
            f"start_steps_missing: {', '.join(missing)}; recover the complete self-deploy capture, including preflight"
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


def find_capture(run_id, project=None):
    """Search only the configured project's deploy watcher captures."""
    name = resolve_active_project(project)
    namespaces = {name}
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    for field in ("id", "slug"):
        response = call_dispatcher(
            function_id="projects.get",
            target=TargetRef(kind="global"),
            payload={"project": name, "field": field},
        )
        if response.success and (response.result or {}).get("value") is not None:
            namespaces.add(str(response.result["value"]))
    from yoke_core.domain.project_scratch_segments import safe_segment

    namespaces = {safe_segment(value) for value in namespaces}
    roots = [global_scratch_root() / namespace / "sessions" for namespace in namespaces]
    candidates = sorted(
        (
            path
            for root in roots
            for path in root.glob("*/runs/*/watcher-captures/yoke-deploy.raw.*.log")
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        with path.open(encoding="utf-8") as stream:
            # The first marker carries the run ID, so unrelated logs are not read whole.
            for line in stream:
                if not line.startswith(PREFIX):
                    continue
                record = json.loads(line[len(PREFIX) :])
                if record.get("run_id") == run_id:
                    return path
                break
    raise StartEvidenceError(
        "start_capture_unavailable: no capture for this run on this machine; run the report on the deploy driver's machine or supply --capture PATH"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=os.environ.get("DEPLOYMENT_RUN_ID"))
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--project")
    parser.add_argument("--baseline-seconds", type=float, required=True)
    args = parser.parse_args(argv)
    if not args.run_id:
        parser.error("--run-id or DEPLOYMENT_RUN_ID is required")
    try:
        capture = args.capture or find_capture(args.run_id, args.project)
        report = start_report(
            capture.read_text(),
            run_id=args.run_id,
            baseline_seconds=args.baseline_seconds,
        )
    except (StartEvidenceError, OSError, ValueError, KeyError, TypeError) as exc:
        reason = (
            str(exc)
            if isinstance(exc, StartEvidenceError)
            else f"start_capture_invalid: {exc}; recover the full raw capture on the execution machine or supply --capture PATH"
        )
        print(f"Deployment start evidence refused: {reason}")
        return 1
    print(json.dumps({**report, "capture": str(capture)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
