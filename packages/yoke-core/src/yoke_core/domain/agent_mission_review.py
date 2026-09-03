"""Main-owned review dispatch for exploratory mission bundles."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.machine_qa_execution import (
    AGENT_MISSION_ARTIFACT_LIMIT,
)
from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE,
)
from yoke_contracts.qa_mission_scratch import mission_scratch_path
from yoke_core.domain.dispatch_descriptors import DispatchDescriptor


def _subject_flag(subject: Mapping[str, Any]) -> str:
    return (
        f"--item-id {int(subject['item_id'])}"
        if subject.get("item_id") is not None
        else f"--deployment-run-id {subject['deployment_run_id']}"
    )


def _screen_recording_warning(cases: list[Mapping[str, Any]]) -> str:
    """Name the Screen Recording grant when mission preparation proved it absent."""
    degraded = [
        case
        for case in cases
        if case.get("capture_runner") == "agent_mission"
        and (
            ((case.get("transcript") or {}).get("preparation") or {}).get("error_code")
        )
        == TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE
    ]
    if not degraded:
        return ""
    requirement_ids = ", ".join(str(int(case["requirement_id"])) for case in degraded)
    return (
        f" WARNING: host-control preparation for case(s) {requirement_ids} "
        f"reported {TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE}: this Mac "
        "cannot produce usable screenshots until a person grants Terminal.app "
        "access under System Settings > Privacy & Security > Screen & System "
        "Audio Recording. Treat screenshot-based findings as unreliable and "
        "prefer transcript, file, and command evidence."
    )


def _walker_dispatch(
    case: Mapping[str, Any],
    *,
    execution_id: str,
    subject_flag: str,
) -> dict[str, Any]:
    descriptor = DispatchDescriptor("qa-walker")
    executor = str(case["executor"])
    host_command_base = (
        f"yoke qa mission host-command {subject_flag} "
        f"--execution-id {execution_id} "
        f"--requirement-id {int(case['requirement_id'])}"
    )
    host_command = f"{host_command_base} -- ARGV..."
    browser_setup_command = (
        f"{host_command_base} [--timeout-seconds N] -- yoke qa browser setup"
    )
    browser_step_command = (
        f"{host_command_base} -- yoke qa browser step --base-url BASE_URL "
        "--step-json STEP_JSON [--output-dir PATH]"
    )
    artifact_add_command = (
        "yoke qa artifact add "
        f"--requirement-id {int(case['requirement_id'])} "
        f"--run-id {int(case['capture_run_id'])} --artifact-type TYPE "
        "--artifact-handle HANDLE_JSON [--content-type TYPE] [--metadata JSON]"
    )
    scratch_path = mission_scratch_path(execution_id)
    scratch_teardown_command = (
        f"yoke qa mission scratch-teardown {subject_flag} "
        f"--execution-id {execution_id} "
        f"--requirement-id {int(case['requirement_id'])}"
    )
    prompt = (
        "Walk this mission atomically. Choose the sequence and use every "
        "available declared substrate that helps. Do not issue the verdict; "
        "return a ranked findings report as the primary deliverable to the "
        "main mission owner. Routine "
        "screen perception is disposable. Attach only deliberate proof of a "
        "finding, never more than "
        f"{AGENT_MISSION_ARTIFACT_LIMIT} artifacts for the entire run using "
        f"`{artifact_add_command}`. Remote commands use `{host_command}`; "
        f"materialize the target browser with `{browser_setup_command}` using "
        "a bounded timeout long enough for first setup, then "
        f"drive it one chosen step at a time with `{browser_step_command}`. "
        "Add `--gui-session` to the outer host command for macOS "
        "window-server or login-keychain work. This lease owns one "
        f"owner-only staging directory on the target, `{scratch_path}`: pipe "
        "a secret on stdin where the product accepts it, and otherwise stage "
        "every file carrying a token or password inside that directory, "
        "never a loose path under /tmp. Before you return, run "
        f"`{scratch_teardown_command}` and state the scratch path and its "
        "confirmed removal in your report; returning while it still exists "
        "is a finding against your own walk. If a permission dialog, "
        "interactive sign-in, or approval needs a person, return immediately "
        "with WALK_STATUS: HUMAN_GATE, the exact needed action, and resume "
        "state. Never wait for the operator inside this turn. On a resumed "
        "walk, read the Progress Log excerpt and resume state supplied by the "
        "main owner before acting. Treat screenshot "
        "display failures, audit-session permission failures, and apparently "
        "expired/unrefreshable OAuth from SSH as wrong-session signals, not "
        "broken credentials." + _screen_recording_warning([case]) + "\n\n"
        f"Mission:\n{case['instructions']}\n\n"
        f"Good outcome:\n{case['expected_outcome']}"
    )
    return {
        "executor": executor,
        "dispatch_kind": (
            descriptor.dispatch_kind
            if executor == "informed_subagent"
            else "target_machine_agent_session"
        ),
        "role": descriptor.role,
        "subagent_type": (
            descriptor.subagent_type if executor == "informed_subagent" else None
        ),
        "context_policy": (
            "project-informed"
            if executor == "informed_subagent"
            else "target-naive-no-checkout"
        ),
        "host_command": host_command,
        "scratch_path": scratch_path,
        "scratch_teardown_command": scratch_teardown_command,
        "browser_setup_command": browser_setup_command,
        "browser_step_command": browser_step_command,
        "artifact_add_command": artifact_add_command,
        "artifact_limit": AGENT_MISSION_ARTIFACT_LIMIT,
        "prompt": prompt,
        "result_schema": {
            "walk_status": "COMPLETE|HUMAN_GATE|UNDETERMINED",
            "report": "ranked findings and unverified areas",
            "needed_action": "required for HUMAN_GATE",
            "resume_state": "required for HUMAN_GATE",
        },
    }


def agent_mission_dispatch_contract(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Return instructions that keep mission ownership in the main agent."""
    bundle_id = str(bundle["bundle_id"])
    digest = str(bundle["bundle_digest"])
    execution_id = str(bundle["execution_id"])
    subject = bundle["subject"]
    subject_flag = _subject_flag(subject)
    execution_target = bundle.get("execution_target")
    target_digest = str(bundle.get("execution_target_digest") or "")
    environment = (
        execution_target.get("environment")
        if isinstance(execution_target, Mapping)
        else None
    )
    authority_bound = (
        isinstance(environment, Mapping)
        and bool(str(environment.get("name") or "").strip())
        and bool(target_digest)
    )
    authority = {
        "state": "bound" if authority_bound else "unavailable",
        "environment": (
            str(environment.get("name") or "") if authority_bound else None
        ),
        "execution_target_digest": target_digest if authority_bound else None,
    }
    cases = list(bundle["cases"])
    walker_dispatches = [
        {
            "requirement_id": int(case["requirement_id"]),
            **_walker_dispatch(
                case,
                execution_id=execution_id,
                subject_flag=subject_flag,
            ),
        }
        for case in cases
        if case.get("capture_runner") == "agent_mission"
    ]
    main_review_requirement_ids = [
        int(case["requirement_id"])
        for case in cases
        if case.get("capture_runner") != "agent_mission"
    ]
    artifact_read_commands = [
        "yoke qa artifact read "
        f"--requirement-id {int(case['requirement_id'])} "
        f"--artifact-id {int(artifact['id'])}"
        for case in cases
        for artifact in case.get("artifacts", [])
    ]
    if authority_bound:
        prompt = (
            f"Own exploratory QA bundle {bundle_id} ({digest}) as the main "
            f"agent for immutable environment {authority['environment']} at "
            f"target digest {target_digest}. Dispatch each case according to "
            "its executor. A walker turn is atomic and cannot ask the operator. "
            "When it returns HUMAN_GATE, append the exact action and resume "
            "state to the item's Progress Log, ask the operator in the main "
            "channel, then include that state when dispatching a fresh walker. "
            "Do not top up "
            "a target-naive session with project checkout or project context. "
            "Review every non-mission case yourself from its transcript and "
            "artifact-read commands. Aggregate each ranked written mission "
            "report, choose every final verdict, and submit exactly one row "
            f"for each of the {len(cases)} bundle cases in one complete batch. "
            "Undetermined halts the item for owner/operator review, so choose "
            "it only with attached evidence and name what remains undecidable."
            + _screen_recording_warning(cases)
        )
        submit_command = (
            f"yoke qa plan review-submit {subject_flag} "
            f"--execution-id {execution_id} --bundle-id {bundle_id} "
            f"--bundle-digest {digest} --stdin"
        )
    else:
        prompt = (
            f"QA bundle {bundle_id} ({digest}) has no immutable target "
            "authority. Preserve it as historical evidence; do not dispatch "
            "walkers, access the leased host, or submit verdicts."
        )
        submit_command = None
        walker_dispatches = []
    return {
        "dispatch_kind": "main_agent_mission",
        "role": "main_agent",
        "subagent_type": None,
        "authority": authority,
        "walker_dispatches": walker_dispatches,
        "main_review_requirement_ids": main_review_requirement_ids,
        "artifact_limit": AGENT_MISSION_ARTIFACT_LIMIT,
        "artifact_read_commands": artifact_read_commands,
        "result_schema": {
            "verdicts": [
                {
                    "requirement_id": "integer",
                    "verdict": "pass|fail|undetermined",
                    "rationale": "non-empty written report",
                }
            ]
        },
        "prompt": prompt,
        "submit_command": submit_command,
    }


__all__ = ["agent_mission_dispatch_contract"]
