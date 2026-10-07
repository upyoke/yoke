"""Terminal checks in the installer Machine QA plan."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.installer_campaign_plan_common import (
    APPLY_SUCCESS_TEXT,
    BROWSER_APPROVAL_TEXT,
    BROWSER_PRIMARY_POST_CHECKS,
    CHOOSE_BACKLOG_KEYS,
    CHOOSE_MACHINE_ONLY_KEYS,
    DUAL_HOST_BASELINES,
    FRESH_HOST,
    HOSTED_ONBOARD,
    MACHINE_GITHUB_TEXT,
    PARENT_HANDOFF_TEXT,
    PATH_READY_TEXT,
    PATH_REPAIR_COMMAND,
    PUBLIC_INSTALL,
    PUBLIC_INSTALL_LOCAL,
    REVIEW_TEXT,
    SECRET_SAFE_POST_CHECKS,
    SHELL_PRECONFIGURED,
    action,
    current_release_setup,
    terminal_case,
    terminal_recipe,
    transition,
)


def _browser_approval_actions() -> list[dict[str, Any]]:
    return [
        action("browser-approval"),
        transition(
            "operator-browser-approval",
            "Enter",
            operator_gate="machine_browser_approval",
            completion_text=MACHINE_GITHUB_TEXT,
            gate_timeout_seconds=600,
        ),
        action("machine-github"),
    ]


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
    actions.append(action("path-diagnosis"))
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
            *_browser_approval_actions(),
            transition("machine-github-backlog", *CHOOSE_BACKLOG_KEYS),
            action("project-mode"),
            transition(
                "project-mode-machine-only",
                *CHOOSE_MACHINE_ONLY_KEYS,
                wait_seconds=10,
            ),
            action("review"),
            transition("apply", "Enter"),
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
        else PATH_READY_TEXT
    )
    return terminal_recipe(
        actions=_hosted_completion_actions(
            path_needs_repair=path_needs_repair,
            uv_needs_install=uv_needs_install,
        ),
        expected_text=(
            "Starting Yoke setup",
            *path_text,
            *BROWSER_APPROVAL_TEXT,
            *MACHINE_GITHUB_TEXT,
            *REVIEW_TEXT,
            *APPLY_SUCCESS_TEXT,
            *PARENT_HANDOFF_TEXT,
        ),
        capture_checkpoints=(
            "browser-approval",
            "review",
            "apply-complete",
            "complete-onboarding",
        ),
        notes=(
            "Run the public {{environment_display_name}} installer through browser-approved hosted "
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
        "Run the public {{environment_display_name}} installer; connect to {{app_url}}. Let the Test Machine's "
        "visible Safari approve the one-time code automatically; no operator browser "
        "action is needed or wanted. Finish onboarding and the parent handoff for both "
        "PATH states. Parallel manual approval consumes the code and breaks the gate."
    ),
    expected_outcome=(
        "Both host baselines complete browser-approved {{environment_display_name}} onboarding with "
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
    entry_surface=PUBLIC_INSTALL,
    required_completion="complete-onboarding",
)


HOSTED_CONNECT = terminal_case(
    4,
    "hosted-connect",
    "terminal-check",
    instructions=(
        "Launch the current installed release against the {{environment_display_name}} hosted "
        "platform, use the browser approval path, and continue only after the "
        "automated Safari approval has granted the one-time machine "
        "authorization. No operator browser action is needed."
    ),
    expected_outcome=(
        "The browser approval screen opens the {{environment_display_name}} platform and advances "
        "directly to GitHub setup with compact verified-connection status, "
        "without asking for a pasted token."
    ),
    method_config=terminal_recipe(
        actions=(
            action("path-ready", ready_text=PATH_READY_TEXT),
            transition("continue-path", "Enter", wait_seconds=10),
            *_browser_approval_actions(),
        ),
        expected_text=(
            "Yoke is already on your PATH.",
            *BROWSER_APPROVAL_TEXT,
            *MACHINE_GITHUB_TEXT,
        ),
        capture_checkpoints=("browser-approval", "machine-github"),
        notes=(
            "Use the live {{environment_display_name}} browser-approval protocol; the setup clears "
            "stored auth temporarily so credential reuse cannot bypass it."
        ),
        setup_operations=current_release_setup(
            "hosted-connect",
            clear_auth=True,
            path_ready=True,
        ),
        post_checks=BROWSER_PRIMARY_POST_CHECKS,
    ),
    entry_surface=HOSTED_ONBOARD,
    required_completion="machine-github",
    host_baselines=(FRESH_HOST,),
)


PATH_REPAIR = terminal_case(
    5,
    "path-repair",
    "terminal-check",
    instructions=(
        "Install the current public {{environment_display_name}} release, run the uv-delegated PATH "
        "repair command, and verify fresh-login shell resolution."
    ),
    expected_outcome=(
        "uv updates shell configuration and the actual login-shell probe reports verified."
    ),
    method_config=terminal_recipe(
        actions=(action("path-repaired"),),
        expected_text=(
            '"login_verified": true',
            '"command": "uv tool update-shell"',
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
    starting_state="inherit",
)


APPLY_HANDOFF = terminal_case(
    6,
    "apply-handoff",
    "terminal-check",
    instructions=(
        "Run the public {{environment_display_name}} installer with the local-machine destination, "
        "create or verify the local universe, stay disabled for GitHub, "
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
            transition("apply", "Enter"),
            action("apply-complete"),
            transition("exit-apply-success", "Enter", wait_seconds=5),
            action("complete-onboarding"),
        ),
        expected_text=(
            "Starting Yoke setup",
            "Yoke is already on your PATH.",
            "Your Yoke lives on this machine.",
            *REVIEW_TEXT,
            *APPLY_SUCCESS_TEXT,
            *PARENT_HANDOFF_TEXT,
        ),
        capture_checkpoints=(
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
    entry_surface=PUBLIC_INSTALL_LOCAL,
    required_completion="complete-onboarding",
    starting_state="inherit",
)


TERMINAL_CHECK_CASES = (
    COLD_START_HOSTED,
    HOSTED_CONNECT,
    PATH_REPAIR,
    APPLY_HANDOFF,
)


__all__ = ["TERMINAL_CHECK_CASES"]
