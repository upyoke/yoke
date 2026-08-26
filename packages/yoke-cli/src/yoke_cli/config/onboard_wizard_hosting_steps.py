"""Body builders and option rows for the wizard's Hosting step.

The Hosting screens are their own module because they are the one place the
wizard shows a credential's custody rules alongside the action that collects
it: the connect screen carries the one-click link, both boxes of the pair, and
where the pair will live; the verified screen carries redacted evidence and
the CI-federation promise. Both are shaped by hand rather than through the
generic selection/verification bodies so that copy stays intact.
"""

from __future__ import annotations

from rich.markup import escape
from textual.widgets import Static

from yoke_cli.config import onboard_input_validation as input_validation
from yoke_cli.config.onboard_wizard_input_entry import form_field_widgets
from yoke_cli.config.onboard_wizard_palette import ACCENT
from yoke_cli.config.onboard_wizard_state import _FormField
from yoke_cli.config.onboard_wizard_widgets import SelectionList, SelectionRow

HOSTING_CONNECT_TITLE = "Connect your hosting provider?"
# One line on purpose: the screen already carries two credential boxes and
# three rows, and a second subtitle line pushes the rows below the fold —
# which would hide the very answer this step exists to offer.
HOSTING_CONNECT_SUBTITLE = (
    "AWS is the one Yoke can run for you; hosting it yourself is a fine answer."
)

# The screen for the operator who runs their own hosting. It asks for nothing
# Yoke needs, because Yoke will not touch that host; the one field exists so
# the project record says where the code actually runs.
HOSTING_NO_MANAGED_HOST_TITLE = "Yoke will manage no host for this project."
HOSTING_PROVIDER_NOTE_FIELD = _FormField(
    key="provider-note",
    label="Where does it run? (optional)",
    placeholder="Render, a DigitalOcean droplet, dokku, an on-prem box...",
)
HOSTING_NO_MANAGED_HOST_FIELDS = (HOSTING_PROVIDER_NOTE_FIELD,)
HOSTING_NO_MANAGED_HOST_ROWS = [
    SelectionRow("record", "Record it & continue", "no credential, no infra"),
    SelectionRow("back", "Back", "connect a hosting provider after all"),
]

# The two halves of one credential, collected together: they are minted by the
# same click and are useless apart, so the screen that explains them is also the
# screen that takes them.
HOSTING_ACCESS_KEY_FIELD = _FormField(
    key="access-key-id",
    label="Access key ID",
    placeholder="AKIA...",
    validate=input_validation.validate_access_key_id,
)
HOSTING_SECRET_KEY_FIELD = _FormField(
    key="secret-access-key",
    label="Secret access key",
    placeholder="the secret value from the stack",
    password=True,
    validate=input_validation.validate_secret_access_key,
)
HOSTING_CREDENTIAL_FIELDS = (HOSTING_ACCESS_KEY_FIELD, HOSTING_SECRET_KEY_FIELD)

HOSTING_CONNECT_ROWS = [
    SelectionRow("connect", "Save & verify", "redacted caller-identity check"),
    SelectionRow("no-managed-host", "I host this myself",
                 "Yoke applies no infrastructure"),
    SelectionRow("skip", "Decide later", "/yoke onboard asks again"),
]
HOSTING_VERIFIED_ROWS = [
    SelectionRow("continue", "Continue to Review", "last step"),
]
HOSTING_RETRY_ROWS = [
    SelectionRow("retry", "Re-enter the two values", "paste them again"),
    SelectionRow("no-managed-host", "I host this myself",
                 "Yoke applies no infrastructure"),
    SelectionRow("skip", "Decide later", "/yoke onboard asks again"),
]
# The AWS CLI is only the verifier — its absence never invalidates a credential
# the operator already pasted, so keeping it unverified is the leading row.
HOSTING_UNVERIFIED_ROWS = [
    SelectionRow("keep", "Keep it without verifying", "check it later with yoke aws exec"),
    SelectionRow("retry", "Re-enter the two values", "paste them again"),
    SelectionRow("no-managed-host", "I host this myself",
                 "Yoke applies no infrastructure"),
    SelectionRow("skip", "Decide later", "/yoke onboard asks again"),
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
    """The connect screen: how to mint the pair, where to paste it, where it lives."""
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
        Static("", classes="onboard-spacer"),
        *form_field_widgets(HOSTING_CREDENTIAL_FIELDS),
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


def hosting_no_managed_host_body() -> list[Static]:
    """The declared-elsewhere screen: what Yoke stops doing, and one prose line."""
    return [
        Static(HOSTING_NO_MANAGED_HOST_TITLE, classes="onboard-title"),
        Static("", classes="onboard-subtitle"),
        Static(
            "  Yoke records the decision and stops proposing hosting:",
            classes="onboard-plan-line",
        ),
        Static(
            "  no cloud credential, no infrastructure Packs, no cloud apply.",
            classes="onboard-plan-line",
        ),
        Static("", classes="onboard-spacer"),
        Static(
            "  Merging, verification, and the delivery loop are unaffected.",
            classes="onboard-subtitle",
        ),
        Static("", classes="onboard-spacer"),
        *form_field_widgets(HOSTING_NO_MANAGED_HOST_FIELDS),
        Static(
            "  Kept as a note on the project so future readers know where it "
            "runs.",
            classes="onboard-subtitle",
        ),
        Static("", classes="onboard-spacer"),
        SelectionList(HOSTING_NO_MANAGED_HOST_ROWS),
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
    "HOSTING_ACCESS_KEY_FIELD",
    "HOSTING_CONNECT_ROWS",
    "HOSTING_CONNECT_SUBTITLE",
    "HOSTING_CONNECT_TITLE",
    "HOSTING_CREDENTIAL_FIELDS",
    "HOSTING_NO_MANAGED_HOST_FIELDS",
    "HOSTING_NO_MANAGED_HOST_ROWS",
    "HOSTING_NO_MANAGED_HOST_TITLE",
    "HOSTING_PROVIDER_NOTE_FIELD",
    "HOSTING_RETRY_ROWS",
    "HOSTING_SECRET_KEY_FIELD",
    "HOSTING_UNVERIFIED_ROWS",
    "HOSTING_VERIFIED_ROWS",
    "NO_LINK_LINE",
    "hosting_connect_body",
    "hosting_error_body",
    "hosting_no_managed_host_body",
    "hosting_verified_body",
]
