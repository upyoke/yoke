"""Per-requirement Browser QA loop using the stable parent patching surface."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from yoke_contracts.browser_qa_contract import (
    BROWSER_CHECK_METHOD,
    BROWSER_INSPECTION_METHOD,
    BrowserMethodContractViolation,
    browser_method_contract_violation,
    case_viewport,
    is_browser_assertion,
)
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain.browser_qa_results import RequirementOutcome, RunResult
from yoke_core.domain.browser_qa_step_artifacts import record_step_artifacts
from yoke_core.domain.qa_artifacts import artifact_directory
from yoke_core.domain.qa_constants import INVALID_BROWSER_METHOD_LABEL


def _process_requirement(
    *,
    req_row: Dict[str, Any],
    subject: int | str,
    project: str,
    base_url: str,
    code_identity: Dict[str, str],
    freshness_validated: bool,
    actor: Optional[ActorContext] = None,
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
    method_id = req_row.get("method_id")
    method_config_raw = req_row["method_config"]

    method_label = {
        "browser-check": "Browser check",
        "browser-inspection": "Browser inspection",
    }.get(method_id, INVALID_BROWSER_METHOD_LABEL)
    _bqa._log(f"Processing requirement {req_id} ({method_label})...")

    # Parse the materialized method configuration.
    steps = []
    method_config: Dict[str, Any] = {}
    if method_config_raw:
        try:
            method_config = json.loads(method_config_raw)
            steps = method_config.get("steps", [])
        except json.JSONDecodeError:
            pass

    # The size this case is authored at. It is resolved before anything opens
    # a page, because a page is sized when it is created rather than adjusted
    # once a case is already looking at it.
    viewport = case_viewport(method_config)
    violation = (
        browser_method_contract_violation(str(method_id or ""), steps)
        if steps else None
    )
    if violation is None and isinstance(viewport, BrowserMethodContractViolation):
        violation = viewport
    if not steps or violation is not None:
        error_code = violation.code if violation else "missing_steps"
        note = violation.message if violation else "method_config has no 'steps'"
        error = f"malformed_method_config:{error_code}"
        _bqa._log(
            f"WARNING: Invalid method_config for requirement {req_id}: {note}"
        )

        run_id = _bqa._record_run(
            req_id, qa_kind, "error",
            _bqa._build_run_payload(
                project=project,
                base_url=base_url,
                code_identity=code_identity,
                freshness_validated=freshness_validated,
                verdict="error",
                errors=error,
                note=f"Skipped: {note}",
            ),
            actor=actor,
        )
        run_result = RunResult(
            requirement_id=req_id,
            qa_kind=qa_kind,
            verdict="error",
            qa_run_id=run_id,
            errors=error,
            code_identity=dict(code_identity),
        )
        return RequirementOutcome(run_result=run_result, skipped=True)

    _bqa._log(f"Found {len(steps)} steps for requirement {req_id}")

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
        actor=actor,
    )
    _bqa._log(f"Created qa_run {run_id}")

    # Create artifact directory
    artifact_dir = str(artifact_directory(project, subject, run_id))
    os.makedirs(artifact_dir, exist_ok=True)

    # capture writes execution_status; verdict is assigned only on capture
    # failures (so the failure is visible in gates that filter verdict='fail').
    # Successful captures land with verdict=NULL until screenshot inspection
    # sets it via a later yoke qa run complete call.
    # This case's own page, open for exactly as long as the case runs. Every
    # step addresses it by id, so no other run is ever handed this screen and
    # this case never inherits one: the route and the width it establishes are
    # its own from its first step to its last.
    page_id = ""
    page_open_error = ""
    try:
        page_id = _bqa.open_owned_page(viewport)
    except RuntimeError as exc:
        page_open_error = str(exc)
        steps = []

    run_execution_status = "captured"
    run_verdict: Optional[str] = None
    run_artifacts: List[str] = []
    run_artifact_ids: List[int] = []
    step_errors = ""
    current_route = "/"
    expected_screenshots = 0
    recorded_screenshots = 0
    expected_assertions = 0
    passed_assertions = 0
    env_failure = False

    def _mark_capture_failed(reason: str) -> None:
        nonlocal run_execution_status, run_verdict, step_errors
        run_execution_status = "capture_failed"
        run_verdict = "fail"
        step_errors += reason

    if page_open_error:
        _bqa._log(
            f"ERROR: this case could not open its own browser page: "
            f"{page_open_error}"
        )
        _mark_capture_failed(f"page_open_failure:{page_open_error};")
        env_failure = True

    for step_idx, step in enumerate(steps):
        assertion_expected = is_browser_assertion(step)
        if assertion_expected:
            expected_assertions += 1
        # Update current route from navigate steps
        if isinstance(step, dict) and step.get("action") == "navigate":
            route = step.get("route", "")
            if route:
                current_route = route

        screenshot_expected = _bqa._is_screenshot_step(step)
        if screenshot_expected:
            expected_screenshots += 1

        _bqa._log(f"  Step {step_idx}: executing...")

        response = _bqa._execute_step(step, base_url, artifact_dir, page_id)

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

        # The step's own account of the page it ran on travels with every
        # capture it produced.
        step_artifacts = record_step_artifacts(
            artifact_paths=list(artifacts_raw),
            step_index=step_idx,
            screenshot_expected=screenshot_expected,
            run_id=run_id,
            requirement_id=req_id,
            qa_kind=qa_kind,
            subject=subject,
            route=current_route,
            label=step.get("label"),
            viewport=data.get("viewport") if isinstance(data, dict) else None,
            observed_url=str(data.get("url") or "") if isinstance(data, dict) else "",
            actor=actor,
        )
        run_artifacts.extend(step_artifacts.paths)
        run_artifact_ids.extend(step_artifacts.artifact_ids)
        if step_artifacts.failures:
            _mark_capture_failed(step_artifacts.failures)

        if (
            screenshot_expected
            and step_artifacts.recorded
            and not step_artifacts.failures
        ):
            recorded_screenshots += 1

        if not step_artifacts.failures:
            _bqa._log(f"  Step {step_idx}: OK")
            if assertion_expected:
                passed_assertions += 1

    # The case is over, so its page goes with it. Leaving it open would leave
    # a signed-in screen around for nothing to inherit, which is exactly the
    # state this ownership exists to end.
    if page_id:
        try:
            _bqa.close_owned_page(page_id)
        except RuntimeError as exc:
            _bqa._log(f"Warning: this case's browser page did not close: {exc}")

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
    # Browser checks decide automatically when every declared step succeeds.
    # Browser inspections remain verdict-less until the plan's batch reviewer.
    if run_verdict is None and method_id == BROWSER_CHECK_METHOD:
        if passed_assertions == expected_assertions:
            run_verdict = "pass"
        else:
            _mark_capture_failed(
                "assertion_completeness:"
                f"expected={expected_assertions},passed={passed_assertions};"
            )
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
            requirement_id=req_id,
            artifact_ids=run_artifact_ids,
            expected_screenshots=expected_screenshots,
            recorded_screenshots=recorded_screenshots,
        ),
        actor=actor,
    )
    _bqa._log(
        f"Requirement {req_id}: execution_status={run_execution_status}, "
        f"verdict={run_verdict}"
    )

    run_result = RunResult(
        requirement_id=req_id,
        qa_kind=qa_kind,
        verdict="pending"
        if method_id == BROWSER_INSPECTION_METHOD
        and run_execution_status == "captured"
        and run_verdict is None
        else run_verdict or "",
        qa_run_id=run_id,
        execution_status=run_execution_status,
        artifacts=run_artifacts,
        artifact_ids=run_artifact_ids,
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
