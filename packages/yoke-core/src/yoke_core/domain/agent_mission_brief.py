"""Walker briefs for leased-host and controller exploratory missions."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.machine_qa_execution import (
    AGENT_MISSION_ARTIFACT_LIMIT,
)
from yoke_contracts.machine_qa_terminal_bridge import (
    TERMINAL_SCREEN_RECORDING_REQUIRED_ERROR_CODE,
)
from yoke_core.domain.agent_mission_browser_identities import (
    walker_identity_dispatch,
)


from yoke_contracts.qa_case_starting_state import needs_test_machine


def _identity_flag(preferred: str | None) -> str:
    """The setup/step identity flag: the project default when offered."""
    return f"--identity {preferred}" if preferred else "[--identity NAME]"


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


def _deployment_run_clause(execution_target: Mapping[str, Any]) -> str:
    """Name the deployment run, environment and commit a release walk tests.

    Empty unless the walk belongs to a deployment run. The prompt's own
    ``--run-id`` flags name the capture run, so this one is labelled apart.
    """
    deployment = execution_target.get("deployment") or {}
    run_id = str(deployment.get("run_id") or "").strip()
    if not run_id:
        return ""
    environment = str(
        (execution_target.get("environment") or {}).get("name") or ""
    ).strip()
    commit = str(deployment.get("release_lineage") or "").strip()
    facts = [f"deployment run {run_id}"]
    if environment:
        facts.append(f"environment {environment}")
    if commit:
        facts.append(f"commit {commit}")
    return (
        f"This walk tests {', '.join(facts)}. The --run-id in the commands "
        "below is this walk's capture run, not the deployment run. "
    )


def _operator_identity(browser_settings: Mapping[str, Any]) -> str:
    """The project's default identity, which every test machine signs in."""
    from yoke_contracts.browser_identity import (
        BrowserIdentityError,
        declared_default_identity,
    )

    try:
        return declared_default_identity(browser_settings) or "OPERATOR_IDENTITY"
    except BrowserIdentityError:
        return "OPERATOR_IDENTITY"


def _walker_dispatch(
    case: Mapping[str, Any],
    *,
    execution_id: str,
    subject_flag: str,
    browser_settings: Mapping[str, Any],
    execution_target: Mapping[str, Any],
) -> dict[str, Any]:
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
    identities, browser_verify_commands, identity_clause, preferred = (
        walker_identity_dispatch(
            case,
            host_command_base,
            browser_settings=browser_settings,
            execution_target=execution_target,
        )
    )
    flag = _identity_flag(preferred)
    browser_setup_command = (
        f"{host_command_base} [--timeout-seconds N] -- yoke qa browser setup "
        f"--project PROJECT {flag}"
    )
    browser_step_command = (
        f"{host_command_base} -- yoke qa browser step --base-url BASE_URL "
        f"--step-json STEP_JSON {flag} [--page NAME] [--output-dir PATH] [--check-id ID] [--keep-open]"
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
        _deployment_run_clause(execution_target)
        + f"Before any other host command, run `{walk_start_command}`: it puts "
        "the Test Machine in this mission's declared starting state. On "
        "mission_walk_already_started, continue with host-command. For another "
        "start failure, record its error and recovery as your blocker. "
        "Walk in this session's main thread. Clean up everything the walk "
        "creates with the product's own commands, even when the walk stops "
        "early, and report anything left. Run walk-end when the walk finishes "
        "or settles early. Choose the sequence and use each declared substrate "
        "that helps. If another item holds a required host, submit `host_wait` "
        "through this bundle with the test machine name and lease evidence. "
        "Record OS package changes through the declared starting-state fixture. "
        "Use host-command for host access. On a clean walk, attach one "
        "deliberate proof of the good outcome as evidence. "
        "Attach deliberate proof of a "
        "finding, never more than "
        f"{AGENT_MISSION_ARTIFACT_LIMIT} artifacts for the entire run using "
        f"`{artifact_add_command}`. For every artifact, "
        f"{artifact_bytes_clause}"
        f"Remote commands use `{host_command}`. "
        f"{browser_intro}"
        + f"`{browser_setup_command}` with a bounded first-setup timeout, then use "
        f"`{browser_step_command}`. "
        f"{identity_clause}Keep the setup response's check_id for this mission; "
        "pass --check-id ID --keep-open on intermediate steps. Omit --keep-open "
        "on the final step, or close early with yoke qa browser stop --check-id ID. "
        + (
            ""
            if identities
            else "Otherwise open each page with "
            f"`{host_command_base} -- yoke browser open --project PROJECT "
            f"--identity {_operator_identity(browser_settings)} URL`: a visible "
            "window of the test machine's operator identity, already signed in, "
            "never the stock desktop browser. Drive it with screenshots and "
            "keystrokes through the remote command. "
        )
        + "Never install Yoke on a Test Machine to get a browser. "
        "Add `--gui-session` to the outer host command for macOS "
        "window-server or login-keychain work. This lease owns one "
        "owner-only staging directory on the target, the `scratch_path` "
        "walk-start prints in its `preparation`; its location depends on "
        "the target's operating system. Pipe a secret on stdin where the "
        "product accepts it, and otherwise stage every file carrying a token "
        "or password inside that directory, never a loose path in a temp "
        "directory. Before you return, run "
        f"`{walk_end_command}`: it removes that directory, restores the "
        "declared starting state, and records the restore on this mission's "
        "run. State the scratch removal and the restore in your report; "
        "returning before it succeeds is a finding against your own walk. "
        "For a real password, 2FA or payment step, ask the human gate "
        "yourself: use the bundle's steering preview and item owner route, "
        "request a reply to this session and park. When the reply arrives, "
        "verify the action and continue at the recorded resume point. Treat screenshot "
        "display failures, audit-session permission failures, and apparently "
        "expired/unrefreshable OAuth from SSH as wrong-session signals, not "
        "broken credentials." + _screen_recording_warning([case]) + "\n\n"
        f"Mission:\n{case['instructions']}\n\n"
        f"Good outcome:\n{case['expected_outcome']}"
    )
    return {
        "executor": executor,
        "host_command": host_command,
        "host_copy_command": host_copy_command,
        "walk_start_command": walk_start_command,
        "walk_end_command": walk_end_command,
        "browser_setup_command": browser_setup_command,
        "browser_step_command": browser_step_command,
        "browser_identities": identities,
        "browser_verify_commands": browser_verify_commands,
        "artifact_add_command": artifact_add_command,
        "artifact_limit": AGENT_MISSION_ARTIFACT_LIMIT,
        "prompt": prompt,
    }


def _controller_dispatch(case, browser_settings, execution_target) -> dict[str, Any]:
    identities, verify_commands, identity_clause, preferred = walker_identity_dispatch(
        case,
        None,
        browser_settings=browser_settings,
        execution_target=execution_target,
    )
    flag = _identity_flag(preferred)
    setup = f"yoke qa browser setup --project PROJECT {flag}"
    step = f"yoke qa browser step --base-url BASE_URL --step-json STEP_JSON {flag} [--page NAME] [--check-id ID] [--keep-open]"
    artifact_command = (
        f"yoke qa artifact add --requirement-id {int(case['requirement_id'])} "
        f"--run-id {int(case['capture_run_id'])} --artifact-type TYPE "
        "--content-file LOCAL_PATH [--filename NAME] [--metadata JSON]"
    )
    return {
        "executor": case.get("executor"),
        "location": "controller",
        "browser_identities": identities,
        "browser_verify_commands": verify_commands,
        "browser_setup_command": setup,
        "browser_step_command": step,
        "artifact_add_command": artifact_command,
        "artifact_limit": AGENT_MISSION_ARTIFACT_LIMIT,
        "prompt": (
            _deployment_run_clause(execution_target)
            + "Explore this mission on the controller, the machine running the main "
            "session. It has no Test Machine lease and owes no host reset or restore. "
            f"Use the controller's declared tools and browser; managed setup: `{setup}`, "
            f"then `{step}`. {identity_clause}Pass the setup check_id with --check-id ID --keep-open "
            "on intermediate steps; omit --keep-open on the last step, or use "
            "yoke qa browser stop --check-id ID before returning. Record ranked findings "
            "with evidence and submit your verdict. Clean up fixtures "
            "you create with the product's own commands and report anything left. "
            f"Attach at most {AGENT_MISSION_ARTIFACT_LIMIT} deliberate proof artifacts "
            f"with `{artifact_command}`. On a clean walk, attach one deliberate proof "
            "of the good outcome as evidence before returning the report, within "
            "the same artifact limit. If evidence lives elsewhere, return a blocker "
            "naming the case change that declares that host. For a real password, "
            "2FA or payment step, ask the human gate yourself through the bundle's "
            "steering preview and item owner route, request a reply to this "
            "session and park. "
            f"\n\nMission:\n{case['instructions']}\n\nGood outcome:\n{case['expected_outcome']}"
        ),
    }
