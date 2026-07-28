"""Terminal inspections in the installer Machine QA plan."""

from __future__ import annotations

from yoke_core.domain.installer_campaign_plan_common import (
    BROWSER_APPROVAL_TEXT,
    BROWSER_PRIMARY_POST_CHECKS,
    CHOOSE_BACKLOG_KEYS,
    HOSTED_STAGE_ONBOARD,
    PUBLIC_STAGE_WELCOME,
    REVIEW_TEXT,
    action,
    current_release_setup,
    terminal_case,
    terminal_recipe,
    transition,
)


WELCOME_FRAME = terminal_case(
    2,
    "welcome-frame",
    "terminal-inspection",
    instructions=(
        "Open the public Stage installer in Terminal and inspect the authored "
        "welcome frame with a process-local minimal macOS system PATH that "
        "intentionally excludes user-installed uv/uvx, before accepting the "
        "product's prerequisite offer."
    ),
    expected_outcome=(
        "The real installer deterministically presents Yoke's authored identity "
        "and uv/uvx prerequisite offer without changing the host, with text "
        "evidence and a screenshot or an explicit capture-degraded reason."
    ),
    method_config=terminal_recipe(
        actions=(action("welcome-frame", wait_seconds=3),),
        expected_text=(
            "Your operating system for software delivery",
            "Yoke's only prerequisite",
            "isn't installed yet.",
        ),
        capture_checkpoints=("welcome-frame",),
        notes=(
            "The live public installer runs with HOME=/var/empty and the "
            "minimal macOS system PATH, excluding both ~/.local/bin and "
            "Homebrew; stopping before consent makes no host mutation."
        ),
        start_delay=0.5,
    ),
    entry_surface=PUBLIC_STAGE_WELCOME,
    required_completion="welcome-frame",
)


CONNECT_WAIT = terminal_case(
    7,
    "connect-wait",
    "terminal-inspection",
    instructions=(
        "Open a fresh Stage browser authorization from the current installed "
        "release and inspect the Terminal frame while approval is pending."
    ),
    expected_outcome=(
        "The Terminal shows the one-time code, browser URL, and explicit "
        "continue-after-approval instruction without exposing a credential."
    ),
    method_config=terminal_recipe(
        actions=(
            action("path-ready"),
            transition("continue-path", "Enter", wait_seconds=10),
            action("connect-wait"),
        ),
        expected_text=(
            "Yoke is already on your PATH.",
            *BROWSER_APPROVAL_TEXT,
        ),
        capture_checkpoints=("connect-wait",),
        notes=(
            "Stop at the current browser-approval wait frame; do not fabricate "
            "approval or fall back to token paste."
        ),
        setup_operations=current_release_setup(
            "connect-wait",
            clear_auth=True,
            path_ready=True,
        ),
        post_checks=BROWSER_PRIMARY_POST_CHECKS,
    ),
    entry_surface=HOSTED_STAGE_ONBOARD,
    required_completion="connect-wait",
)


REVIEW_FRAME = terminal_case(
    8,
    "review-frame",
    "terminal-inspection",
    instructions=(
        "Approve the live Stage machine authorization in the browser, stay "
        "backlog-only for GitHub, and inspect the machine-only Review frame "
        "without choosing Apply."
    ),
    expected_outcome=(
        "Review names the pending writes and presents Apply as the primary "
        "action only after browser approval has produced a verified connection."
    ),
    method_config=terminal_recipe(
        actions=(
            action("path-ready"),
            transition("continue-path", "Enter", wait_seconds=10),
            action("browser-approval"),
            transition("operator-browser-approval", wait_seconds=180),
            transition("poll-browser-approval", "Enter", wait_seconds=20),
            action("hosted-connected"),
            transition("continue-hosted-connected", "Enter"),
            action("machine-github"),
            transition(
                "machine-github-backlog",
                *CHOOSE_BACKLOG_KEYS,
                wait_seconds=10,
            ),
            action("review-frame"),
        ),
        expected_text=(
            *BROWSER_APPROVAL_TEXT,
            "Yoke token connected.",
            *REVIEW_TEXT,
        ),
        capture_checkpoints=("browser-approval", "review-frame"),
        notes=(
            "Inspect Review after a real browser-approved connection; the case "
            "ends before Apply and never substitutes a stored or pasted token."
        ),
        setup_operations=current_release_setup(
            "review-frame",
            clear_auth=True,
            path_ready=True,
        ),
        post_checks=BROWSER_PRIMARY_POST_CHECKS,
        step_delay=4,
    ),
    entry_surface=HOSTED_STAGE_ONBOARD,
    required_completion="review-frame",
)


TERMINAL_INSPECTION_CASES = (
    WELCOME_FRAME,
    CONNECT_WAIT,
    REVIEW_FRAME,
)


__all__ = ["TERMINAL_INSPECTION_CASES"]
