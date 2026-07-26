"""Body builders and option rows for the wizard's Hosting step.

The Hosting screens are their own module because they are the one place the
wizard shows a credential's custody rules alongside the action that collects
it: the connect screen carries the one-click link, the paste directive, and
where the pair will live; the verified screen carries redacted evidence and
the CI-federation promise. Both are shaped by hand rather than through the
generic selection/verification bodies so that copy stays intact.
"""

from __future__ import annotations

from rich.markup import escape
from textual.widgets import Static

from yoke_cli.config.onboard_wizard_palette import ACCENT
from yoke_cli.config.onboard_wizard_widgets import SelectionList, SelectionRow

HOSTING_CONNECT_TITLE = "Connect your hosting provider?"
HOSTING_CONNECT_SUBTITLE = (
    "AWS for now. One click creates the deploy credential; paste its two "
    "values below."
)
HOSTING_ACCESS_KEY_TITLE = "Paste the access key ID."
HOSTING_ACCESS_KEY_SUBTITLE = (
    "The AKIA... value from the stack — here in the wizard, never into an AI chat."
)
HOSTING_SECRET_KEY_TITLE = "Paste the secret access key."
HOSTING_SECRET_KEY_SUBTITLE = (
    "Hidden as you type. Stored owner-only on this machine, never echoed back."
)

HOSTING_CONNECT_ROWS = [
    SelectionRow("connect", "Save & verify", "redacted caller-identity check"),
    SelectionRow("skip", "Skip for now", "connect later via /yoke onboard or re-run"),
]
HOSTING_VERIFIED_ROWS = [
    SelectionRow("continue", "Continue to Review", "last step"),
]
HOSTING_RETRY_ROWS = [
    SelectionRow("retry", "Re-enter the two values", "paste them again"),
    SelectionRow("skip", "Skip for now", "connect later via /yoke onboard or re-run"),
]
# The AWS CLI is only the verifier — its absence never invalidates a credential
# the operator already pasted, so keeping it unverified is the leading row.
HOSTING_UNVERIFIED_ROWS = [
    SelectionRow("keep", "Keep it without verifying", "check it later with yoke aws exec"),
    SelectionRow("retry", "Re-enter the two values", "paste them again"),
    SelectionRow("skip", "Skip for now", "connect later via /yoke onboard or re-run"),
]

# Fallback for a build with no published bootstrap template (a source
# checkout): naming the command is honest where inventing a URL would not be.
NO_LINK_LINE = (
    "run `yoke aws admin-link` from an installed Yoke build for the one-click link"
)


def hosting_connect_body(
    *,
    quick_create_url: str | None,
    credential_dir: str,
) -> list[Static]:
    """The connect screen: how to mint the pair, and where it will live."""
    link_line = quick_create_url or NO_LINK_LINE
    return [
        Static(HOSTING_CONNECT_TITLE, classes="onboard-title"),
        Static(HOSTING_CONNECT_SUBTITLE, classes="onboard-subtitle"),
        Static("", classes="onboard-spacer"),
        Static(
            "  1  Open the one-click link (creates the IAM user + access key):",
            classes="onboard-plan-line",
        ),
        Static(f"     [{ACCENT}]{escape(link_line)}[/]", classes="onboard-plan-line"),
        Static("", classes="onboard-spacer"),
        Static(
            "  2  Paste the two values — here in the wizard, never into an AI chat:",
            classes="onboard-plan-line",
        ),
        Static(
            "     Access key ID first, then the secret access key.",
            classes="onboard-plan-line",
        ),
        Static("", classes="onboard-spacer"),
        Static(
            f"  Stays on this machine ({escape(credential_dir)}) —",
            classes="onboard-subtitle",
        ),
        Static(
            "  operator-attended; CI only ever gets scoped OIDC roles minted later.",
            classes="onboard-subtitle",
        ),
        Static("", classes="onboard-spacer"),
        SelectionList(HOSTING_CONNECT_ROWS),
    ]


def hosting_verified_body(
    *,
    account: str,
    identity: str,
    credential_dir: str,
) -> list[Static]:
    """The verified screen: redacted evidence, custody, and the way forward."""
    return [
        Static(
            f"[{ACCENT}]✔ aws-admin saved · verified with a redacted "
            "caller-identity check[/]",
            classes="onboard-title",
        ),
        Static("", classes="onboard-spacer"),
        Static(f"  Account       {escape(account)}", classes="onboard-plan-line"),
        Static(
            f"  Identity      {escape(identity)}  (IAM user)",
            classes="onboard-plan-line",
        ),
        Static(
            f"  Stored at     {escape(credential_dir)}", classes="onboard-plan-line",
        ),
        Static("", classes="onboard-spacer"),
        Static(
            "CI never sees this key — deploys federate through short-lived OIDC "
            "roles that Yoke",
            classes="onboard-subtitle",
        ),
        Static(
            "provisions from it during /yoke onboard.", classes="onboard-subtitle",
        ),
        Static("", classes="onboard-spacer"),
        SelectionList(HOSTING_VERIFIED_ROWS),
    ]


def hosting_error_body(
    title: str,
    message: str,
    detail_lines: list[str],
    rows: list[SelectionRow],
) -> list[Static]:
    """One error convention with the other steps: bold red ✗, calm detail."""
    widgets = [
        Static(f"✗ {escape(title)}", classes="onboard-title-error"),
        Static("", classes="onboard-spacer"),
        Static(escape(message), classes="onboard-plan-line"),
    ]
    widgets.extend(
        Static(f"  • {escape(line)}", classes="onboard-plan-line")
        for line in detail_lines
    )
    widgets.append(Static("", classes="onboard-spacer"))
    widgets.append(SelectionList(rows))
    return widgets


__all__ = [
    "HOSTING_ACCESS_KEY_SUBTITLE",
    "HOSTING_ACCESS_KEY_TITLE",
    "HOSTING_CONNECT_ROWS",
    "HOSTING_CONNECT_SUBTITLE",
    "HOSTING_CONNECT_TITLE",
    "HOSTING_RETRY_ROWS",
    "HOSTING_SECRET_KEY_SUBTITLE",
    "HOSTING_SECRET_KEY_TITLE",
    "HOSTING_UNVERIFIED_ROWS",
    "HOSTING_VERIFIED_ROWS",
    "NO_LINK_LINE",
    "hosting_connect_body",
    "hosting_error_body",
    "hosting_verified_body",
]
