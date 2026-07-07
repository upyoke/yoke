"""Per-requirement browser QA step loop."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from yoke_harness import browser_client
from yoke_harness.browser_qa_artifacts import (
    artifact_directory,
    build_metadata,
    complete_run,
    durable_artifact_handle,
    record_artifact,
    record_run,
)
from yoke_harness.browser_qa_checks import build_run_payload, is_screenshot_step
from yoke_harness.browser_qa_results import (
    Dispatcher,
    RequirementOutcome,
    RunResult,
)


@dataclass
class RequirementState:
    run_execution_status: str = "captured"
    run_verdict: Optional[str] = None
    run_artifacts: List[str] = None  # type: ignore[assignment]
    step_errors: str = ""
    expected_screenshots: int = 0
    recorded_screenshots: int = 0
    env_failure: bool = False

    def __post_init__(self) -> None:
        if self.run_artifacts is None:
            self.run_artifacts = []

    def mark_capture_failed(self, reason: str) -> None:
        self.run_execution_status = "capture_failed"
        self.run_verdict = "fail"
        self.step_errors += reason

    def outcome(
        self,
        req_id: int,
        qa_kind: str,
        run_id: Optional[int],
        code_identity: Dict[str, str],
    ) -> RequirementOutcome:
        return RequirementOutcome(
            run_result=RunResult(
                requirement_id=req_id,
                qa_kind=qa_kind,
                verdict=self.run_verdict or "",
                qa_run_id=run_id,
                execution_status=self.run_execution_status,
                artifacts=self.run_artifacts,
                errors=self.step_errors,
                expected_screenshots=self.expected_screenshots,
                recorded_screenshots=self.recorded_screenshots,
                code_identity=dict(code_identity),
            ),
            executed=True,
            capture_failed=(self.run_execution_status == "capture_failed"),
            env_failure=self.env_failure,
        )


def process_requirement(
    *,
    dispatcher: Dispatcher,
    req_row: Dict[str, Any],
    item_id: int,
    project: str,
    base_url: str,
    code_identity: Dict[str, str],
    freshness_validated: bool,
) -> RequirementOutcome:
    req_id = int(req_row["id"])
    qa_kind = str(req_row["qa_kind"])
    steps = parse_steps(req_row.get("success_policy"))
    if not steps:
        return skipped_requirement(
            dispatcher, req_id, qa_kind, project, base_url,
            code_identity, freshness_validated,
        )

    run_id = record_run(
        dispatcher,
        req_id,
        qa_kind,
        raw_result=build_run_payload(
            project=project,
            base_url=base_url,
            code_identity=code_identity,
            freshness_validated=freshness_validated,
            note="started",
        ),
    )
    artifact_dir = str(artifact_directory(project, item_id, run_id or 0))
    os.makedirs(artifact_dir, exist_ok=True)
    state = RequirementState()
    current_route = "/"

    for step_idx, step in enumerate(steps):
        if isinstance(step, dict) and step.get("action") == "navigate":
            current_route = step.get("route") or current_route
        screenshot_expected = is_screenshot_step(step)
        if screenshot_expected:
            state.expected_screenshots += 1
        response = execute_step(step, base_url, artifact_dir)
        if response.get("exit_code") == 2:
            state.mark_capture_failed(f"step_{step_idx}:env_setup_failure;")
            state.env_failure = True
            break
        process_step_artifacts(
            dispatcher, response, screenshot_expected, state, step_idx,
            run_id or 0, req_id, qa_kind, item_id, current_route,
        )

    if (
        state.expected_screenshots > 0
        and state.recorded_screenshots < state.expected_screenshots
        and state.run_execution_status == "captured"
    ):
        state.mark_capture_failed(
            f"screenshot_completeness:expected={state.expected_screenshots},"
            f"recorded={state.recorded_screenshots};"
        )
    complete_requirement_run(
        dispatcher, state, run_id or 0, req_id, project, base_url,
        code_identity, freshness_validated,
    )
    return state.outcome(req_id, qa_kind, run_id, code_identity)


def parse_steps(success_policy_raw: Any) -> List[Dict[str, Any]]:
    if not success_policy_raw:
        return []
    try:
        parsed_policy = json.loads(success_policy_raw)
    except json.JSONDecodeError:
        return []
    steps = parsed_policy.get("steps", [])
    return steps if isinstance(steps, list) else []


def skipped_requirement(
    dispatcher: Dispatcher,
    req_id: int,
    qa_kind: str,
    project: str,
    base_url: str,
    code_identity: Dict[str, str],
    freshness_validated: bool,
) -> RequirementOutcome:
    run_id = record_run(
        dispatcher,
        req_id,
        qa_kind,
        "error",
        build_run_payload(
            project=project,
            base_url=base_url,
            code_identity=code_identity,
            freshness_validated=freshness_validated,
            verdict="error",
            errors="malformed_success_policy:missing_steps",
            note="Skipped: success_policy missing 'steps' array",
        ),
    )
    return RequirementOutcome(
        run_result=RunResult(
            requirement_id=req_id,
            qa_kind=qa_kind,
            verdict="error",
            qa_run_id=run_id,
            errors="malformed_success_policy:missing_steps",
            code_identity=dict(code_identity),
        ),
        skipped=True,
    )


def process_step_artifacts(
    dispatcher: Dispatcher,
    response: Dict[str, Any],
    screenshot_expected: bool,
    state: RequirementState,
    step_idx: int,
    run_id: int,
    req_id: int,
    qa_kind: str,
    item_id: int,
    current_route: str,
) -> None:
    data = response.get("data", response)
    if not response.get("success", True):
        data_error = data.get("error") if isinstance(data, dict) else "unknown"
        error = response.get("error", data_error)
        state.mark_capture_failed(f"step_{step_idx}:{error};")
        return
    if (
        isinstance(data, dict)
        and data is not response
        and not data.get("success", True)
    ):
        state.mark_capture_failed(
            f"step_{step_idx}:{data.get('error', 'step_failed')};"
        )
        return
    artifacts_raw = data.get("artifacts", []) if isinstance(data, dict) else []
    if not artifacts_raw:
        screenshot = (
            data.get("screenshot") if isinstance(data, dict) else None
        ) or response.get("screenshot")
        if screenshot:
            artifacts_raw = [screenshot]
    if screenshot_expected and not artifacts_raw:
        state.mark_capture_failed(f"step_{step_idx}:no_screenshot_artifact;")
        return

    valid_artifact = False
    artifact_failure = False
    for artifact_path in artifacts_raw:
        if not os.path.isfile(str(artifact_path)):
            if screenshot_expected:
                state.mark_capture_failed(f"step_{step_idx}:artifact_not_on_disk;")
                artifact_failure = True
            continue
        handle = durable_artifact_handle(
            dispatcher, run_id, req_id, str(artifact_path), "image/png",
        )
        art_id = record_artifact(
            dispatcher,
            run_id,
            req_id,
            "screenshot",
            "image/png",
            handle,
            json.dumps(build_metadata(step_idx, qa_kind, item_id, current_route)),
        )
        if art_id:
            state.run_artifacts.append(os.path.abspath(str(artifact_path)))
            valid_artifact = True
    if screenshot_expected and valid_artifact and not artifact_failure:
        state.recorded_screenshots += 1


def complete_requirement_run(
    dispatcher: Dispatcher,
    state: RequirementState,
    run_id: int,
    req_id: int,
    project: str,
    base_url: str,
    code_identity: Dict[str, str],
    freshness_validated: bool,
) -> None:
    complete_run(
        dispatcher,
        run_id,
        req_id,
        verdict=state.run_verdict,
        execution_status=state.run_execution_status,
        raw_result=build_run_payload(
            project=project,
            base_url=base_url,
            code_identity=code_identity,
            freshness_validated=freshness_validated,
            verdict=state.run_verdict,
            execution_status=state.run_execution_status,
            errors=state.step_errors,
            artifacts=state.run_artifacts,
            expected_screenshots=state.expected_screenshots,
            recorded_screenshots=state.recorded_screenshots,
        ),
    )


def execute_step(
    step_json: Dict[str, Any],
    base_url: str,
    artifact_dir: str,
) -> Dict[str, Any]:
    if not browser_client.daemon_running():
        return {"success": False, "error": "env_setup_failure", "exit_code": 2}
    try:
        return browser_client.execute_step(step_json, base_url, output_dir=artifact_dir)
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}


__all__ = ["process_requirement"]
