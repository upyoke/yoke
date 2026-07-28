"""Terminal checks in the installer Machine QA plan."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.installer_campaign_plan_common import (
    APPLY_SUCCESS_TEXT,
    BROWSER_APPROVAL_TEXT,
    BROWSER_PRIMARY_POST_CHECKS,
    CHOOSE_BACKLOG_KEYS,
    CHOOSE_MACHINE_ONLY_KEYS,
    CHOOSE_STAGE_KEYS,
    DUAL_HOST_BASELINES,
    FRESH_HOST,
    HOSTED_STAGE_ONBOARD,
    PARENT_HANDOFF_TEXT,
    PATH_REPAIR_COMMAND,
    PUBLIC_STAGE_INSTALL,
    PUBLIC_STAGE_INSTALL_LOCAL,
    REVIEW_TEXT,
    SECRET_SAFE_POST_CHECKS,
    SHELL_PRECONFIGURED,
    action,
    current_release_setup,
    terminal_case,
    terminal_recipe,
    transition,
)


def _hosted_completion_actions(
    *,
    path_needs_repair: bool,
    uv_needs_install: bool,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if uv_needs_install:
        actions.append(transition("uv-consent", "Enter", wait_seconds=90))
    else:
        actions.append(transition("installer-running", wait_seconds=45))
    actions.extend(
        [
            action("install-summary"),
            transition("continue-install-summary", "Enter"),
            action("path-diagnosis"),
        ]
    )
    if path_needs_repair:
        actions.extend(
            [
                transition("apply-path-fix", "Enter", wait_seconds=5),
                action("path-verified"),
                transition("continue-path-verified", "Enter"),
            ]
        )
    else:
        actions.append(transition("continue-path", "Enter"))
    actions.extend(
        [
            action("destination-picker-frame"),
            transition(
                "destination-picker",
                *CHOOSE_STAGE_KEYS,
                wait_seconds=10,
            ),
            action("browser-approval"),
            transition("operator-browser-approval", wait_seconds=180),
            transition("poll-browser-approval", "Enter", wait_seconds=20),
            action("hosted-connected"),
            transition("continue-hosted-connected", "Enter"),
            action("machine-github"),
            transition("machine-github-backlog", *CHOOSE_BACKLOG_KEYS),
            action("project-mode"),
            transition(
                "project-mode-machine-only",
                *CHOOSE_MACHINE_ONLY_KEYS,
                wait_seconds=10,
            ),
            action("review"),
            transition("apply", "Enter", wait_seconds=120),
            action("apply-complete"),
            transition("exit-apply-success", "Enter", wait_seconds=5),
            action("complete-onboarding"),
        ]
    )
    return actions


def _cold_start_config(
    *,
    baseline: str,
    path_needs_repair: bool,
    uv_needs_install: bool,
) -> dict[str, Any]:
    path_text = (
        ("Add Yoke to your PATH.", "Added Yoke to your PATH.")
        if path_needs_repair
        else ("Yoke is already on your PATH.",)
    )
    return terminal_recipe(
        actions=_hosted_completion_actions(
            path_needs_repair=path_needs_repair,
            uv_needs_install=uv_needs_install,
        ),
        expected_text=(
            "Starting Yoke onboard",
            *path_text,
            "Where should this Yoke live?",
            *BROWSER_APPROVAL_TEXT,
            "Yoke token connected.",
            *REVIEW_TEXT,
            *APPLY_SUCCESS_TEXT,
            *PARENT_HANDOFF_TEXT,
        ),
        capture_checkpoints=(
            "install-summary",
            "browser-approval",
            "review",
            "apply-complete",
            "complete-onboarding",
        ),
        notes=(
            "Run the public Stage installer through browser-approved hosted "
            f"onboarding and the parent installer handoff from {baseline}."
        ),
        post_checks=(
            *BROWSER_PRIMARY_POST_CHECKS,
            "terminal_exit_code:0",
        ),
        start_delay=5,
        step_delay=4,
    )


COLD_START_HOSTED = terminal_case(
    3,
    "cold-start-hosted",
    "terminal-check",
    instructions=(
        "Run the public Stage installer in Terminal, choose stage.upyoke.com, "
        "approve the one-time machine authorization in the browser, finish "
        "machine-only onboarding, Apply, and follow the successful parent "
        "handoff. Prove both registered PATH starting states."
    ),
    expected_outcome=(
        "Both host baselines complete browser-approved Stage onboarding with "
        "exit code 0, an Apply report, and the installer parent handoff; the "
        "fresh host includes PATH repair while the preconfigured shell does not."
    ),
    method_config={
        "baseline_configs": {
            FRESH_HOST: _cold_start_config(
                baseline=FRESH_HOST,
                path_needs_repair=True,
                uv_needs_install=True,
            ),
            SHELL_PRECONFIGURED: _cold_start_config(
                baseline=SHELL_PRECONFIGURED,
                path_needs_repair=False,
                uv_needs_install=False,
            ),
        }
    },
    host_baselines=DUAL_HOST_BASELINES,
    entry_surface=PUBLIC_STAGE_INSTALL,
    required_completion="complete-onboarding",
)


HOSTED_CONNECT = terminal_case(
    4,
    "hosted-connect",
    "terminal-check",
    instructions=(
        "Launch the current installed release against the Stage hosted "
        "platform, use the browser approval path, and continue only after the "
        "one-time machine authorization is approved."
    ),
    expected_outcome=(
        "The browser approval screen opens the Stage platform and returns to a "
        "verified Yoke token connection without asking for a pasted token."
    ),
    method_config=terminal_recipe(
        actions=(
            action("path-ready"),
            transition("continue-path", "Enter", wait_seconds=10),
            action("browser-approval"),
            transition("operator-browser-approval", wait_seconds=180),
            transition("poll-browser-approval", "Enter", wait_seconds=20),
            action("hosted-connected"),
        ),
        expected_text=(
            "Yoke is already on your PATH.",
            *BROWSER_APPROVAL_TEXT,
            "Yoke token connected.",
        ),
        capture_checkpoints=("browser-approval", "hosted-connected"),
        notes=(
            "Use the live Stage browser-approval protocol; the setup clears "
            "stored auth temporarily so credential reuse cannot bypass it."
        ),
        setup_operations=current_release_setup(
            "hosted-connect",
            clear_auth=True,
            path_ready=True,
        ),
        post_checks=BROWSER_PRIMARY_POST_CHECKS,
    ),
    entry_surface=HOSTED_STAGE_ONBOARD,
    required_completion="hosted-connected",
)


PATH_REPAIR = terminal_case(
    5,
    "path-repair",
    "terminal-check",
    instructions=(
        "Install the current public Stage release, run the product-owned PATH "
        "repair command, and verify both fresh-login and SSH shell resolution."
    ),
    expected_outcome=(
        "The managed PATH block is applied idempotently and both the login-shell "
        "and SSH-command probes report verified."
    ),
    method_config=terminal_recipe(
        actions=(action("path-repaired"),),
        expected_text=(
            '"verified": true',
            '"ssh_verified": true',
            '"files":',
        ),
        capture_checkpoints=("path-repaired",),
        notes=(
            "Exercise the product-owned path fix rather than reproducing its "
            "startup-file or tool-directory rules in the campaign."
        ),
        setup_operations=current_release_setup("path-repair"),
        execution_mode="ssh-command",
        start_delay=0,
        step_delay=0.5,
    ),
    entry_surface=PATH_REPAIR_COMMAND,
    required_completion="path-repaired",
)


APPLY_HANDOFF = terminal_case(
    6,
    "apply-handoff",
    "terminal-check",
    instructions=(
        "Run the public Stage installer with the local-machine destination, "
        "create or verify the local universe, stay backlog-only for GitHub, "
        "choose machine-only setup, Apply, exit successfully, and capture the "
        "installer parent's execution-ready handoff."
    ),
    expected_outcome=(
        "The local-machine Apply succeeds with a durable report, the wizard "
        "exits 0, and the public installer prints its parent handoff without "
        "using browser authorization or any API token."
    ),
    method_config=terminal_recipe(
        actions=(
            transition("installer-running", wait_seconds=45),
            action("install-summary"),
            transition("continue-install-summary", "Enter"),
            action("path-diagnosis"),
            transition("continue-path", "Enter"),
            action("local-universe"),
            transition("continue-local-universe", "Enter"),
            transition("machine-github", *CHOOSE_BACKLOG_KEYS),
            transition(
                "project-mode",
                *CHOOSE_MACHINE_ONLY_KEYS,
                wait_seconds=10,
            ),
            action("review"),
            transition("apply", "Enter", wait_seconds=120),
            action("apply-complete"),
            transition("exit-apply-success", "Enter", wait_seconds=5),
            action("complete-onboarding"),
        ),
        expected_text=(
            "Starting Yoke onboard",
            "Yoke is already on your PATH.",
            "Your Yoke lives on this machine.",
            *REVIEW_TEXT,
            *APPLY_SUCCESS_TEXT,
            *PARENT_HANDOFF_TEXT,
        ),
        capture_checkpoints=(
            "install-summary",
            "local-universe",
            "review",
            "apply-complete",
            "complete-onboarding",
        ),
        notes=(
            "Keep the successful local Apply/report/parent-handoff journey "
            "behaviorally distinct from the hosted browser case."
        ),
        setup_operations=current_release_setup(
            "apply-handoff",
            path_ready=True,
        ),
        post_checks=(
            *SECRET_SAFE_POST_CHECKS,
            "no_text:One-time code:",
            "no_text:Paste your Yoke API token.",
            "terminal_exit_code:0",
        ),
        start_delay=5,
        step_delay=4,
    ),
    entry_surface=PUBLIC_STAGE_INSTALL_LOCAL,
    required_completion="complete-onboarding",
)


TERMINAL_CHECK_CASES = (
    COLD_START_HOSTED,
    HOSTED_CONNECT,
    PATH_REPAIR,
    APPLY_HANDOFF,
)


__all__ = ["TERMINAL_CHECK_CASES"]
