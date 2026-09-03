"""The AWS CLI prerequisite screens of the wizard's Hosting step.

Sits between choosing AWS and being asked for anything. The step's own identity
check runs in-process through boto3, so it passes on a machine that cannot run a
single capability-owned AWS command; without this gate an operator could create
an access key, watch Yoke report the identity verified, and finish setup with
the executable that work depends on still missing.

A refusal keeps the operator on the answer they gave. Installing the CLI and
choosing "Check again" continues into AWS exactly where they were; "Back"
returns to the provider question so a different answer is still available;
"Not now" is the only route that leaves hosting undecided, and it is chosen,
never imposed. Nothing is stored and no posture is recorded on this path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yoke_cli.config import aws_cli_prerequisite
from yoke_cli.config import onboard_wizard_hosting_steps as hosting_steps
from yoke_cli.config.onboard_wizard_step_ids import STEP_HOSTING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_flow_hosting import _Shell

PREFLIGHT_TITLE = "Checking the AWS CLI on this machine."
PREFLIGHT_MESSAGE = (
    "Nothing is created or stored while the prerequisite is checked."
)
PREFLIGHT_DETAIL_LINES = [
    "Every AWS operation Yoke runs for you uses this executable.",
]
NOTHING_STORED_LINE = (
    "Nothing was stored, and no AWS identity was recorded."
)


def run_preflight(shell: "_Shell") -> None:
    """Check the AWS CLI, then open the AWS sign-in choice or the refusal."""
    shell._run_checking(
        step=STEP_HOSTING,
        title=PREFLIGHT_TITLE,
        message=PREFLIGHT_MESSAGE,
        detail_lines=list(PREFLIGHT_DETAIL_LINES),
        work=aws_cli_prerequisite.check_aws_cli,
        on_success=lambda _receipt: shell._goto_hosting_aws_sign_in(),
        on_error=lambda exc: _goto_refusal(shell, exc),
        group="onboard-hosting-prerequisite",
        blocks_quit=False,
    )


def _goto_refusal(shell: "_Shell", exc: BaseException) -> None:
    from yoke_cli.config.onboard_wizard_app import _View

    details = [*getattr(exc, "detail_lines", ()), NOTHING_STORED_LINE]
    shell.result.hosting_verification = None
    shell._goto(_View(
        STEP_HOSTING,
        lambda: hosting_steps.hosting_error_body(
            hosting_steps.HOSTING_PREREQUISITE_TITLE,
            str(exc),
            details,
            hosting_steps.HOSTING_PREREQUISITE_ROWS,
        ),
        lambda choice: on_refusal_choice(shell, choice),
    ))


def on_refusal_choice(shell: "_Shell", choice: str) -> Any:
    if choice == "retry":
        run_preflight(shell)
        return None
    if choice == "back":
        import asyncio

        return asyncio.ensure_future(shell.action_back())
    shell._skip_hosting()
    return None


__all__ = [
    "NOTHING_STORED_LINE",
    "PREFLIGHT_DETAIL_LINES",
    "PREFLIGHT_MESSAGE",
    "PREFLIGHT_TITLE",
    "on_refusal_choice",
    "run_preflight",
]
