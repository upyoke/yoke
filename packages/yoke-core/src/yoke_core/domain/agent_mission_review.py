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
from yoke_core.domain.qa_review_evidence import case_artifact_read_commands
from yoke_core.domain.qa_plan_review_subject import subject_flag as review_subject_flag
from yoke_core.domain.qa_review_verdict_modes import (
    ALL_REVIEW_VERDICTS,
    inconclusive_verdict_guidance,
    verdict_enum_text,
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
        f"{host_command_base} [--timeout-seconds N] -- yoke qa browser setup "
        "[--project PROJECT --profile-baseline ABSOLUTE_SEALED_PATH]"
    )
    browser_step_command = (
        f"{host_command_base} -- yoke qa browser step --base-url BASE_URL "
        "--step-json STEP_JSON [--output-dir PATH]"
    )
    walks_on_target = executor != "informed_subagent"
    artifact_bytes_source = (
        "--content-file PATH"
        if walks_on_target
        else "--content-base64 B64 --filename NAME"
    )
    artifact_add_command = (
        "yoke qa artifact add "
        f"--requirement-id {int(case['requirement_id'])} "
        f"--run-id {int(case['capture_run_id'])} --artifact-type TYPE "
        f"{artifact_bytes_source} [--content-type TYPE] [--metadata JSON]"
    )
    artifact_bytes_clause = (
        "attach it with the bytes themselves, never a path on the target: "
        "walk-end restores the host to its declared starting state, so a "
        "recorded path outlives its own file and is refused. "
    ) + (
        ""
        if walks_on_target
        else (
            "You are driving the target from another machine, so read the "
            "bytes back first by running `base64 -i TARGET_PATH` through "
            "the remote command below and passing its stdout as B64. "
        )
    )
    scratch_path = mission_scratch_path(execution_id)
    walk_flags = (
        f"{subject_flag} --execution-id {execution_id} "
        f"--requirement-id {int(case['requirement_id'])}"
    )
    walk_start_command = f"yoke qa mission walk-start {walk_flags}"
    walk_end_command = (
        f"yoke qa mission walk-end {walk_flags} --run-id {int(case['capture_run_id'])}"
    )
    prompt = (
        f"Before any other host command, run `{walk_start_command}`: it puts "
        "the Test Machine in this mission's declared starting state. If it "
        "fails, walk nothing and return its error as your blocker. "
        "Walk this mission atomically. Every Yoke project you create during "
        "the walk is yours to clean up: the moment one exists, append its "
        "slug to the Progress Log of the item this mission verifies "
        "(`yoke items progress-log append PREFIX-N --headline "
        "'QA created project SLUG' --stdin`), so a replacement walker can "
        "finish the cleanup; before returning a pass or failure, retire each "
        "one with your own control-plane CLI (`yoke projects retire --project "
        "SLUG --reason 'QA mission finished'`), never with Yoke on the Test "
        "Machine, and list them in `created_projects`. Report a retirement "
        "blocker as a finding. Choose the sequence and use every "
        "available declared substrate that helps. Do not issue the verdict; "
        "return a ranked findings report as the primary deliverable to the "
        "main mission owner. If another item holds a required host, do nothing "
        "on that host and return WALK_STATUS: HOST_WAIT with its registered "
        "machine name and lease evidence; the main owner submits host_wait, "
        "never fail or undetermined for contention. Record OS package changes "
        "through the declared starting-state fixture; do not use SSH around "
        "this lease. Routine "
        "screen perception is disposable. Attach only deliberate proof of a "
        "finding, never more than "
        f"{AGENT_MISSION_ARTIFACT_LIMIT} artifacts for the entire run using "
        f"`{artifact_add_command}`. For every artifact, "
        f"{artifact_bytes_clause}"
        f"Remote commands use `{host_command}`. "
        "For web interaction, if Yoke is on the target because this walk "
        "installed it, materialize the target browser with "
        f"`{browser_setup_command}` using a bounded timeout long enough for "
        "first setup, then drive it one chosen step at a time with "
        f"`{browser_step_command}`. Otherwise open the host's own browser "
        "(Safari on macOS; the desktop's default browser elsewhere) and "
        "drive it with screenshots and keystrokes through the remote command. "
        "Never install Yoke on a Test Machine to get a browser. "
        "Add `--gui-session` to the outer host command for macOS "
        "window-server or login-keychain work. This lease owns one "
        f"owner-only staging directory on the target, `{scratch_path}`: pipe "
        "a secret on stdin where the product accepts it, and otherwise stage "
        "every file carrying a token or password inside that directory, "
        "never a loose path under /tmp. Before you return, run "
        f"`{walk_end_command}`: it removes that directory, restores the "
        "declared starting state, and records the restore on this mission's "
        "run. State the scratch removal and the restore in your report; "
        "returning before it succeeds is a finding against your own walk. "
        "If a permission dialog, "
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
        "walk_start_command": walk_start_command,
        "walk_end_command": walk_end_command,
        "browser_setup_command": browser_setup_command,
        "browser_step_command": browser_step_command,
        "artifact_add_command": artifact_add_command,
        "artifact_limit": AGENT_MISSION_ARTIFACT_LIMIT,
        "prompt": prompt,
        "result_schema": {
            "walk_status": "COMPLETE|HUMAN_GATE|HOST_WAIT|UNDETERMINED",
            "report": "ranked findings and unverified areas",
            "host_wait": "machine name and holder evidence for HOST_WAIT",
            "created_projects": "slug and retirement result of every Yoke project the walk created",
            "needed_action": "required for HUMAN_GATE",
            "resume_state": "required for HUMAN_GATE",
        },
    }


def agent_mission_dispatch_contract(
    bundle: Mapping[str, Any],
    *,
    allowed_verdicts: tuple[str, ...] = ALL_REVIEW_VERDICTS,
) -> dict[str, Any]:
    """Return instructions that keep mission ownership in the main agent."""
    bundle_id = str(bundle["bundle_id"])
    digest = str(bundle["bundle_digest"])
    execution_id = str(bundle["execution_id"])
    subject = bundle["subject"]
    execution_target = bundle.get("execution_target")
    subject_flag = review_subject_flag(subject, execution_target)
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
    artifact_read_commands = case_artifact_read_commands(cases)
    if authority_bound:
        prompt = (
            f"Own exploratory QA bundle {bundle_id} ({digest}) as the main "
            f"agent for immutable environment {authority['environment']} at "
            f"target digest {target_digest}. Dispatch each case according to "
            "its executor, one walker at a time in the listed order: every "
            "mission shares the plan's one Test Machine, and each walk resets "
            "it on walk-start and restores it on walk-end. A walker turn is "
            "atomic and cannot ask the operator. "
            "When it returns HUMAN_GATE, append the exact action and resume "
            "state to the item's Progress Log, ask the operator in the main "
            "channel, then include that state when dispatching a fresh walker. "
            "Do not top up "
            "a target-naive session with project checkout or project context. "
            "Review every non-mission case yourself from its transcript and "
            "artifact-read commands. Aggregate each ranked written mission "
            "report, choose every final verdict, and submit exactly one row "
            f"for each of the {len(cases)} bundle cases in one complete batch. "
            + inconclusive_verdict_guidance(allowed_verdicts)
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
                    "verdict": verdict_enum_text(allowed_verdicts),
                    "rationale": "non-empty written report",
                }
            ]
        },
        "prompt": prompt,
        "host_wait_schema": {
            "host_wait": {"machine": "registered name", "rationale": "lease evidence"}
        },
        "submit_command": submit_command,
    }


__all__ = ["agent_mission_dispatch_contract"]
