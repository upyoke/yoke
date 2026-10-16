"""Approval screens for browser sign-in: the code, the link, and the wait."""

from __future__ import annotations

from typing import Any

from yoke_contracts.api_urls import HOSTED_STAGE_PLATFORM_URL

from yoke_cli.config import hosted_machine_authorization
from yoke_cli.config.onboard_wizard_flow_machine_admission import approval_hint
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_state import CopyTarget, _View
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT
from yoke_cli.config.setup_prompt import TONE_OK, SetupHuman, SetupPrompt

Pending = hosted_machine_authorization.PendingMachineAuthorization


def browser_status_line(
    browser: hosted_machine_authorization.BrowserOpenResult,
    log_path: object,
) -> str:
    """One line every approval view carries: opened, or why not and where that is logged."""
    if browser.opened:
        return "The browser was opened for you."
    line = (
        f"No browser available here. Open this link on any device. ({browser.reason})"
    )
    if log_path:
        line += f" Logged to {log_path}."
    return line


class HostedMachineApprovalViews:
    """What every step of a browser approval shows and hands to an agent."""

    def _approval_detail_lines(self, pending: Pending, browser_line: str) -> list[str]:
        stage_warning = (
            [
                "Stage is test-only and disposable.",
                "Do not use it for live operations or durable control-plane state.",
            ]
            if pending.platform_url == HOSTED_STAGE_PLATFORM_URL
            else []
        )
        return [
            *stage_warning,
            f"Match code: {pending.user_code}",
            approval_hint(pending.user_code),
            f"Open: {pending.verification_uri_complete}",
            browser_line,
        ]

    def _approval_copy_targets(self, pending: Pending) -> tuple[CopyTarget, ...]:
        return (
            CopyTarget("the match code", pending.user_code),
            CopyTarget(
                "the approval link",
                pending.verification_uri_complete,
                is_url=True,
            ),
        )

    def _approval_human(self, pending: Pending) -> SetupHuman:
        action = (
            "approve this machine"
            if pending.self_host
            else ("sign in, choose an organization, and approve this machine")
        )
        return SetupHuman(
            instructions=(
                f"Open the link, confirm the match code {pending.user_code}, "
                f"then {action}. {approval_hint(pending.user_code)}"
            ),
            url=pending.verification_uri_complete,
            user_code=pending.user_code,
            max_seconds=float(pending.expires_in),
            poll_interval_seconds=float(pending.interval),
        )

    def _goto_hosted_machine_approval(
        self: Any, pending: Pending, browser_line: str
    ) -> None:
        self._goto(
            _View(
                SetupPrompt(
                    key="connect.hosted_machine_approval",
                    step=STEP_CONNECT,
                    title="Sign in and approve your machine."
                    if pending.self_host
                    else "Sign in and choose an organization.",
                    message="Approve this machine in your browser, then continue here.",
                    detail_lines=(
                        *self._approval_detail_lines(pending, browser_line),
                        "One organization is connected at a time; run onboarding "
                        "again to add another.",
                    ),
                    choices=tuple(steps.VERIFY_OK_ROWS),
                    tone=TONE_OK,
                    human=self._approval_human(pending),
                ),
                lambda _choice: self._poll_hosted_machine_authorization(
                    pending,
                    browser_line,
                ),
                copy_targets=self._approval_copy_targets(pending),
            )
        )


__all__ = ["HostedMachineApprovalViews", "browser_status_line"]
