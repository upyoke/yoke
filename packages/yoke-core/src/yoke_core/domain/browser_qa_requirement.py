"""Per-requirement step-loop orchestration for Browser QA.

Owns ``_process_requirement`` — the per-``qa_requirement`` step loop that
``execute_scenario`` calls once per browser-kind row. The loop owns the
``_mark_capture_failed`` closure (the closure's ``nonlocal`` over the
loop-local execution-status/verdict/error variables is load-bearing).

All sibling-helper calls go through the parent ``yoke_core.domain.browser_qa``
module (lazy-imported) so test patches via
``mock.patch.object(browser_qa, "<helper>", ...)`` take effect against this
caller without rebinding sibling-local names.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from yoke_core.domain.browser_qa_results import RunResult
from yoke_core.domain.qa_artifacts import (
    artifact_directory,
    build_metadata,
)


@dataclass
class RequirementOutcome:
    """Outcome of processing a single qa_requirement.

    Returned by ``_process_requirement`` to ``execute_scenario`` so the latter
    can update its aggregate ``ScenarioResult`` (verdict, executed/skipped
    counters, runs list) without sharing mutable state with the loop.
    """

    run_result: RunResult
    skipped: bool = False
    executed: bool = False
    capture_failed: bool = False
    env_failure: bool = False


def _process_requirement(
    *,
    req_row: Dict[str, Any],
    item_id: int,
    project: str,
    base_url: str,
    code_identity: Dict[str, str],
    freshness_validated: bool,
) -> RequirementOutcome:
    """Process a single qa_requirement row end-to-end.

    Returns a ``RequirementOutcome`` describing the resulting qa_run, whether
    it was skipped (malformed policy) or executed, whether capture failed,
    and whether the daemon-level env-setup failure was hit (signal to the
    caller to abort remaining requirements).
    """
    # Lazy import to dodge the circular import with browser_qa and to honor
    # test patches against browser_qa.<helper>.
    from yoke_core.domain import browser_qa as _bqa

    req_id = req_row["id"]
    qa_kind = req_row["qa_kind"]
    success_policy_raw = req_row["success_policy"]

    _bqa._log(f"Processing requirement {req_id} (kind: {qa_kind})...")

    # Parse success_policy
    steps = []
    if success_policy_raw:
        try:
            policy_data = json.loads(success_policy_raw)
            steps = policy_data.get("steps", [])
        except json.JSONDecodeError:
            pass

    if not steps:
        _bqa._log(
            f"WARNING: No steps found in success_policy for requirement {req_id}"
        )

        # Record error run
        run_id = _bqa._record_run(
            req_id, qa_kind, "error",
            _bqa._build_run_payload(
                project=project,
                base_url=base_url,
                code_identity=code_identity,
                freshness_validated=freshness_validated,
                verdict="error",
                errors="malformed_success_policy:missing_steps",
                note="Skipped: success_policy missing 'steps' array",
            ),
        )
        run_result = RunResult(
            requirement_id=req_id,
            qa_kind=qa_kind,
            verdict="error",
            qa_run_id=run_id,
            errors="malformed_success_policy:missing_steps",
            code_identity=dict(code_identity),
        )
        return RequirementOutcome(run_result=run_result, skipped=True)

    _bqa._log(f"Found {len(steps)} steps for requirement {req_id}")

    # Create qa_run
    run_id = _bqa._record_run(
        req_id,
        qa_kind,
        raw_result=_bqa._build_run_payload(
            project=project,
            base_url=base_url,
            code_identity=code_identity,
            freshness_validated=freshness_validated,
            note="started",
        ),
    )
    _bqa._log(f"Created qa_run {run_id}")

    # Create artifact directory
    artifact_dir = str(artifact_directory(project, item_id, run_id))
    os.makedirs(artifact_dir, exist_ok=True)

    # capture writes execution_status; verdict is assigned only on capture
    # failures (so the failure is visible in gates that filter verdict='fail').
    # Successful captures land with verdict=NULL until screenshot inspection
    # sets it via a later yoke qa run complete call.
    run_execution_status = "captured"
    run_verdict: Optional[str] = None
    run_artifacts: List[str] = []
    step_errors = ""
    current_route = "/"
    expected_screenshots = 0
    recorded_screenshots = 0
    env_failure = False

    def _mark_capture_failed(reason: str) -> None:
        nonlocal run_execution_status, run_verdict, step_errors
        run_execution_status = "capture_failed"
        run_verdict = "fail"
        step_errors += reason

    for step_idx, step in enumerate(steps):
        # Update current route from navigate steps
        if isinstance(step, dict) and step.get("action") == "navigate":
            route = step.get("route", "")
            if route:
                current_route = route

        screenshot_expected = _bqa._is_screenshot_step(step)
        if screenshot_expected:
            expected_screenshots += 1

        _bqa._log(f"  Step {step_idx}: executing...")

        response = _bqa._execute_step(
            step, base_url, artifact_dir, run_id, item_id,
            project, current_route, step_idx,
        )

        if response.get("exit_code") == 2:
            _bqa._log(
                f"  Step {step_idx}: daemon not running (exit 2) -- env setup failure"
            )
            _mark_capture_failed(f"step_{step_idx}:env_setup_failure;")
            env_failure = True
            break

        # unwrap daemon data envelope when present.
        # The daemon wraps its payload under a "data" key:
        #   {"success": true, "data": {"success": true, "artifacts": [...]}}
        # Fall back to the response itself for flat/direct shapes.
        data = response.get("data", response)

        # Check outer envelope success first (covers exit_code, transport errors)
        if not response.get("success", True):
            error = response.get("error", data.get("error", "unknown"))
            _bqa._log(f"  Step {step_idx}: FAILED (error={error})")
            _mark_capture_failed(f"step_{step_idx}:{error};")
            continue

        # Check inner data.success for step-level failures.
        if (
            isinstance(data, dict)
            and data is not response
            and not data.get("success", True)
        ):
            error = data.get("error", "step_failed")
            _bqa._log(
                f"  Step {step_idx}: FAILED (inner data.success=false, error={error})"
            )
            _mark_capture_failed(f"step_{step_idx}:{error};")
            continue

        # Extract artifacts from the unwrapped data envelope.
        artifacts_raw = data.get("artifacts", [])
        if not artifacts_raw:
            screenshot = data.get("screenshot") or response.get("screenshot")
            if screenshot:
                artifacts_raw = [screenshot]

        # Screenshot steps must produce an artifact path.
        if screenshot_expected and not artifacts_raw:
            _bqa._log(
                f"  Step {step_idx}: FAILED -- screenshot step returned no artifact path"
            )
            _mark_capture_failed(f"step_{step_idx}:no_screenshot_artifact;")
            continue

        step_had_valid_artifact = False
        step_had_artifact_failure = False
        for apath in artifacts_raw:
            if not os.path.isfile(str(apath)):
                if screenshot_expected:
                    # Screenshot artifact paths must exist on disk.
                    _bqa._log(
                        f"  Step {step_idx}: FAILED -- artifact not on disk: {apath}"
                    )
                    _mark_capture_failed(f"step_{step_idx}:artifact_not_on_disk;")
                    step_had_artifact_failure = True
                else:
                    _bqa._log(f"  SKIPPED artifact (not on disk): {apath}")
                continue

            # Durability is opt-in at the record boundary: presign + upload
            # to the env artifacts bucket when declared, else an explicit
            # local handle on the capture path.
            handle = _bqa._durable_artifact_handle(
                run_id, req_id, str(apath), "image/png",
            )
            metadata = build_metadata(step_idx, qa_kind, item_id, current_route)

            art_id = _bqa._record_artifact(
                run_id, req_id, "screenshot", "image/png",
                handle, json.dumps(metadata),
            )
            if art_id:
                # The capture stays on this machine's disk either way;
                # in-session screenshot inspection reads it from here.
                run_artifacts.append(os.path.abspath(str(apath)))
                step_had_valid_artifact = True

        if (
            screenshot_expected
            and step_had_valid_artifact
            and not step_had_artifact_failure
        ):
            recorded_screenshots += 1

        if not step_had_artifact_failure:
            _bqa._log(f"  Step {step_idx}: OK")

    # Completeness check: expected vs. recorded screenshots.
    if (
        expected_screenshots > 0
        and recorded_screenshots < expected_screenshots
        and run_execution_status == "captured"
    ):
        _bqa._log(
            f"  Screenshot completeness check FAILED: "
            f"expected {expected_screenshots}, recorded {recorded_screenshots}"
        )
        _mark_capture_failed(
            f"screenshot_completeness:expected={expected_screenshots},"
            f"recorded={recorded_screenshots};"
        )

    # finalize with execution_status. verdict is NULL on success
    # (awaiting inspection) and 'fail' on capture failure.
    _bqa._complete_run(
        run_id,
        req_id,
        verdict=run_verdict,
        execution_status=run_execution_status,
        raw_result=_bqa._build_run_payload(
            project=project,
            base_url=base_url,
            code_identity=code_identity,
            freshness_validated=freshness_validated,
            verdict=run_verdict,
            execution_status=run_execution_status,
            errors=step_errors,
            artifacts=run_artifacts,
            expected_screenshots=expected_screenshots,
            recorded_screenshots=recorded_screenshots,
        ),
    )
    _bqa._log(
        f"Requirement {req_id}: execution_status={run_execution_status}, "
        f"verdict={run_verdict}"
    )

    run_result = RunResult(
        requirement_id=req_id,
        qa_kind=qa_kind,
        verdict=run_verdict or "",
        qa_run_id=run_id,
        execution_status=run_execution_status,
        artifacts=run_artifacts,
        errors=step_errors,
        expected_screenshots=expected_screenshots,
        recorded_screenshots=recorded_screenshots,
        code_identity=dict(code_identity),
    )
    return RequirementOutcome(
        run_result=run_result,
        executed=True,
        capture_failed=(run_execution_status == "capture_failed"),
        env_failure=env_failure,
    )
