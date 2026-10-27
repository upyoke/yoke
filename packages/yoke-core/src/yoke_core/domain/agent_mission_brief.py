"""Walker briefs for leased-host and controller exploratory missions."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.machine_qa_execution import (
    AGENT_MISSION_ARTIFACT_LIMIT,
)
from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE,
)
from yoke_contracts.qa_mission_scratch import mission_scratch_path
from yoke_core.domain.agent_mission_browser_identities import (
    walker_identity_dispatch,
)
from yoke_core.domain.dispatch_descriptors import DispatchDescriptor


from yoke_contracts.qa_case_starting_state import needs_test_machine


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
    browser_settings: Mapping[str, Any],
    execution_target: Mapping[str, Any],
) -> dict[str, Any]:
    descriptor = DispatchDescriptor("qa-walker")
    from yoke_core.domain.qa_method_config_validation import validate_method_config

    executor = validate_method_config(
        "agent-mission", {"executor": case.get("executor")}
    )["executor"]
    if not needs_test_machine({**case, "runner_id": "agent_mission"}):
        return _controller_dispatch(case, browser_settings, execution_target)
    mission_flags = (
        f"{subject_flag} --execution-id {execution_id} "
        f"--requirement-id {int(case['requirement_id'])}"
    )
    host_command_base = f"yoke qa mission host-command {mission_flags}"
    host_copy_command = (
        f"yoke qa mission host-copy {mission_flags} --from TARGET_PATH --to LOCAL_PATH"
    )
    host_command = f"{host_command_base} -- ARGV..."
    browser_setup_command = (
        f"{host_command_base} [--timeout-seconds N] -- yoke qa browser setup "
        "--project PROJECT [--identity NAME]"
    )
    browser_step_command = (
        f"{host_command_base} -- yoke qa browser step --base-url BASE_URL "
        "--step-json STEP_JSON [--identity NAME] [--output-dir PATH]"
    )
    identities, browser_verify_commands, identity_clause = walker_identity_dispatch(
        case,
        host_command_base,
        browser_settings=browser_settings,
        execution_target=execution_target,
    )
    artifact_add_command = (
        "yoke qa artifact add "
        f"--requirement-id {int(case['requirement_id'])} "
        f"--run-id {int(case['capture_run_id'])} --artifact-type TYPE "
        "--content-file LOCAL_PATH [--filename NAME] [--content-type TYPE] [--metadata JSON]"
    )
    artifact_bytes_clause = (
        "attach the bytes themselves, never a path on the target. "
        "Copy the file into your own local scratch directory with "
        f"`{host_copy_command}`, then upload it with `--content-file "
        "LOCAL_PATH` from your machine. host-copy refuses paths inside the "
        "mission scratch directory on the target, which holds staged secrets. "
    )
    scratch_path = mission_scratch_path(execution_id)
    walk_start_command = f"yoke qa mission walk-start {mission_flags}"
    run_id = int(case["capture_run_id"])
    walk_end_command = f"yoke qa mission walk-end {mission_flags} --run-id {run_id}"
    browser_intro = (
        "For named browser identities, use the managed browser. Set it up with "
        if identities
        else "For web interaction, if Yoke is on the target because "
        "this walk installed it, materialize the target browser with "
    )
    prompt = (
        f"Before any other host command, run `{walk_start_command}`: it puts "
        "the Test Machine in this mission's declared starting state. If it "
        "fails, walk nothing and return its error as your blocker. "
        "Walk this mission atomically. Clean up everything the walk creates "
        "(repositories, accounts, records the product registered) with the "
        "product's own commands, even when the walk stops early, and report "
        "anything you could not remove. Run walk-end even when the walk "
        "stops early. Choose the sequence and use every "
        "available declared substrate that helps. Do not issue the verdict; "
        "return a ranked findings report as the primary deliverable to the "
        "main mission owner. If another item holds a required host, do nothing "
        "on that host and return WALK_STATUS: HOST_WAIT with its test "
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
        f"{browser_intro}"
        + f"`{browser_setup_command}` with a bounded first-setup timeout, then use "
        f"`{browser_step_command}`. "
        f"{identity_clause}"
        + (
            ""
            if identities
            else "Otherwise open the host's own browser "
            "(Safari on macOS; the desktop's default browser elsewhere) and "
            "drive it with screenshots and keystrokes through the remote command. "
        )
        + "Never install Yoke on a Test Machine to get a browser. "
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
        "If a password or credential entry the agent may not type is needed, "
        "return immediately with WALK_STATUS: HUMAN_GATE naming that one entry "
        "and resume state. Never wait for the operator inside this turn, and never "
        "send, acknowledge, or cancel Fleet mail. On a resumed "
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
        "dispatch_kind": descriptor.dispatch_kind,
        "role": descriptor.role,
        "subagent_type": descriptor.subagent_type,
        "context_policy": "project-informed",
        "host_command": host_command,
        "host_copy_command": host_copy_command,
        "scratch_path": scratch_path,
        "walk_start_command": walk_start_command,
        "walk_end_command": walk_end_command,
        "browser_setup_command": browser_setup_command,
        "browser_step_command": browser_step_command,
        "browser_identities": identities,
        "browser_verify_commands": browser_verify_commands,
        "artifact_add_command": artifact_add_command,
        "artifact_limit": AGENT_MISSION_ARTIFACT_LIMIT,
        "prompt": prompt,
        "result_schema": {
            "walk_status": "COMPLETE|HUMAN_GATE|HOST_WAIT|UNDETERMINED",
            "report": (
                "ranked findings, unverified areas, and anything the walk "
                "created but could not remove"
            ),
            "host_wait": "test machine name and holder evidence for HOST_WAIT",
            "needed_action": "required for HUMAN_GATE",
            "resume_state": "required for HUMAN_GATE",
        },
    }


def _controller_dispatch(case, browser_settings, execution_target) -> dict[str, Any]:
    descriptor = DispatchDescriptor("qa-walker")
    identities, verify_commands, identity_clause = walker_identity_dispatch(
        case,
        None,
        browser_settings=browser_settings,
        execution_target=execution_target,
    )
    setup = "yoke qa browser setup --project PROJECT [--identity NAME]"
    step = "yoke qa browser step --base-url BASE_URL --step-json STEP_JSON [--identity NAME]"
    artifact_command = (
        f"yoke qa artifact add --requirement-id {int(case['requirement_id'])} "
        f"--run-id {int(case['capture_run_id'])} --artifact-type TYPE "
        "--content-file LOCAL_PATH [--filename NAME] [--metadata JSON]"
    )
    return {
        "executor": case.get("executor"),
        "dispatch_kind": descriptor.dispatch_kind,
        "role": descriptor.role,
        "subagent_type": descriptor.subagent_type,
        "context_policy": "project-informed",
        "location": "controller",
        "browser_identities": identities,
        "browser_verify_commands": verify_commands,
        "browser_setup_command": setup,
        "browser_step_command": step,
        "artifact_add_command": artifact_command,
        "artifact_limit": AGENT_MISSION_ARTIFACT_LIMIT,
        "prompt": (
            "Explore this mission on the controller, the machine running the main "
            "session. It has no Test Machine lease and owes no host reset or restore. "
            f"Use the controller's declared tools and browser; managed setup: `{setup}`, "
            f"then `{step}`. {identity_clause}Return ranked findings "
            "with evidence to the main owner, who owns the verdict. Clean up fixtures "
            "you create with the product's own commands and report anything left. "
            f"Attach at most {AGENT_MISSION_ARTIFACT_LIMIT} deliberate proof artifacts "
            f"with `{artifact_command}`. If evidence lives elsewhere, return a blocker "
            "naming the case change that declares that host. Real password, 2FA or "
            "payment steps return HUMAN_GATE with the entry and resume state; never "
            "wait for the operator or send Fleet mail. "
            f"\n\nMission:\n{case['instructions']}\n\nGood outcome:\n{case['expected_outcome']}"
        ),
        "result_schema": {
            "walk_status": "COMPLETE|HUMAN_GATE|UNDETERMINED",
            "report": "ranked findings and evidence",
            "needed_action": "required for HUMAN_GATE",
            "resume_state": "required for HUMAN_GATE",
        },
    }
