"""Terminal inspections in the installer Machine QA plan."""

from __future__ import annotations

from yoke_core.domain.installer_campaign_plan_common import (
    BROWSER_APPROVAL_TEXT,
    BROWSER_PRIMARY_POST_CHECKS,
    CHOOSE_BACKLOG_KEYS,
    HOSTED_ONBOARD,
    MACHINE_GITHUB_TEXT,
    PUBLIC_WELCOME,
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
        "Open the public {{environment_display_name}} installer in Terminal and inspect the authored "
        "welcome frame with a process-local minimal macOS system PATH that "
        "intentionally excludes user-installed uv/uvx, capturing the automatic "
        "uv install status line and the diagnosed refusal to write the "
        "read-only home (no confirmation prompt to accept)."
    ),
    expected_outcome=(
        "The real installer deterministically presents Yoke's authored identity "
        "and attempts uv installation, then exits 1 with the named uv "
        "installation failure and its manual-install recovery. Capture text "
        "and a screenshot or an explicit capture-degraded reason."
    ),
    method_config=terminal_recipe(
        actions=(action("welcome-frame", wait_seconds=3),),
        expected_text=(
            "Your operating system for software delivery",
            "Installing uv",
            "uv installation failed. Install uv manually",
            "then rerun: curl -fsSL",
        ),
        capture_checkpoints=("welcome-frame",),
        notes=(
            "The live public installer runs with HOME=/var/empty and the "
            "minimal macOS system PATH, excluding both ~/.local/bin and "
            "Homebrew; uv installs automatically with no confirmation, so the "
            "isolated /var/empty home (not a stopped-before-consent gate) is "
            "what keeps this case from mutating the real host. The expected "
            "exit 1 must include the diagnosed uv failure and recovery; an "
            "unrelated download or installer failure is not a passing frame."
        ),
        expected_return_codes=(1,),
        start_delay=0.5,
    ),
    entry_surface=PUBLIC_WELCOME,
    required_completion="welcome-frame",
    starting_state="as_is",
    starting_state_reason=(
        "The installer runs with HOME=/var/empty and a minimal system PATH, so "
        "it neither reads nor changes the host user's state"
    ),
)


CONNECT_WAIT = terminal_case(
    7,
    "connect-wait",
    "terminal-inspection",
    instructions=(
        "Open a fresh {{environment_display_name}} browser authorization from the current installed "
        "release and inspect the Terminal frame while approval is pending."
    ),
    expected_outcome=(
        "The Terminal shows the Match code, browser URL, and explicit "
        "continue-after-approval instruction without exposing a credential."
    ),
    method_config=terminal_recipe(
        actions=(
            action(
                "connect-wait",
                ready_text=BROWSER_APPROVAL_TEXT,
                ready_timeout_seconds=180,
            ),
        ),
        expected_text=(*BROWSER_APPROVAL_TEXT,),
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
    entry_surface=HOSTED_ONBOARD,
    required_completion="connect-wait",
    starting_state="inherit",
)


REVIEW_FRAME = terminal_case(
    8,
    "review-frame",
    "terminal-inspection",
    instructions=(
        "Let the Test Machine's visible Safari session automatically approve the "
        "live {{environment_display_name}} machine authorization; no operator browser action is "
        "needed or wanted. Stay disabled for GitHub and inspect the machine-only "
        "Review frame without choosing Apply. A parallel manual approval "
        "consumes the Match code and breaks the automated gate."
    ),
    expected_outcome=(
        "Review names the pending writes and presents Apply as the primary "
        "action only after browser approval has produced a verified connection."
    ),
    method_config=terminal_recipe(
        actions=(
            action(
                "browser-approval",
                ready_text=BROWSER_APPROVAL_TEXT,
                ready_timeout_seconds=180,
            ),
            transition(
                "operator-browser-approval",
                "Enter",
                operator_gate="machine_browser_approval",
                completion_text=MACHINE_GITHUB_TEXT,
                gate_timeout_seconds=600,
            ),
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
            *MACHINE_GITHUB_TEXT,
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
    entry_surface=HOSTED_ONBOARD,
    required_completion="review-frame",
    starting_state="inherit",
)


TERMINAL_INSPECTION_CASES = (
    WELCOME_FRAME,
    CONNECT_WAIT,
    REVIEW_FRAME,
)


__all__ = ["TERMINAL_INSPECTION_CASES"]
