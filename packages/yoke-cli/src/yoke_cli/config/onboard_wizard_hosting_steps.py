"""Body builders and option rows for the wizard's Hosting step.

Provider choice and AWS sign-in choice are deliberately separate. Credential
entry then shares one field pair, custody explanation, verification action,
and outcome regardless of whether Yoke guided creation or the operator brought
an existing access key.
"""

from __future__ import annotations

from rich.markup import escape
from textual.widgets import Static

from yoke_cli.config import onboard_input_validation as input_validation
from yoke_cli.config.onboard_wizard_input_entry import form_field_widgets
from yoke_cli.config.onboard_wizard_palette import ACCENT
from yoke_cli.config.onboard_wizard_state import _FormField
from yoke_cli.config.onboard_wizard_widgets import SelectionList, SelectionRow

HOSTING_PROVIDER_TITLE = "Connect your hosting provider?"
HOSTING_PROVIDER_SUBTITLE = (
    "AWS is the one Yoke can run for you; hosting it yourself is a fine answer."
)
HOSTING_PROVIDER_ROWS = [
    SelectionRow("aws", "AWS", "Yoke can manage its infrastructure"),
    SelectionRow(
        "no-managed-host", "I host this myself", "Yoke applies no infrastructure",
    ),
    SelectionRow("skip", "Decide later", "/yoke onboard asks again"),
]

HOSTING_AWS_SIGN_IN_TITLE = "How should Yoke sign in to AWS?"
HOSTING_AWS_SIGN_IN_SUBTITLE = "Choose an access-key path Yoke can execute today."
HOSTING_AWS_SIGN_IN_ROWS = [
    SelectionRow(
        "create-key", "Create a dedicated deploy key", "Recommended",
    ),
    SelectionRow(
        "existing-key", "Use existing credentials", "An access key you manage",
    ),
    SelectionRow("skip", "Not now", "Continue without AWS credentials"),
]

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

HOSTING_CREDENTIAL_ROWS = [
    SelectionRow("connect", "Save & verify", "Confirm the AWS identity"),
    SelectionRow("skip", "Not now", "Continue without AWS credentials"),
]
HOSTING_VERIFIED_ROWS = [
    SelectionRow("continue", "Continue to Review", "last step"),
]
HOSTING_RETRY_ROWS = [
    SelectionRow("retry", "Re-enter the two values", "paste them again"),
    SelectionRow("skip", "Not now", "Continue without AWS credentials"),
]

# The AWS branch needs the AWS CLI before it is worth asking for a key, so this
# screen comes between choosing AWS and entering anything. "Back" is offered
# explicitly rather than left to the keyboard: an operator who cannot install
# the CLI right now still gets to give a different hosting answer instead of
# being pushed into "decide later" as the only way out.
HOSTING_PREREQUISITE_TITLE = "Yoke needs the AWS CLI before it asks for a key."
HOSTING_PREREQUISITE_ROWS = [
    SelectionRow("retry", "Check again", "after installing the AWS CLI"),
    SelectionRow("back", "Back", "give a different hosting answer"),
    SelectionRow("skip", "Not now", "/yoke onboard asks again"),
]

HOSTING_GUIDED_KEY_TITLE = "Create a dedicated deploy key"
HOSTING_GUIDED_KEY_SUBTITLE = (
    "New to AWS? Create an account at aws.amazon.com first, then return here."
)
HOSTING_EXISTING_KEY_TITLE = "Use existing credentials"
HOSTING_EXISTING_KEY_SUBTITLE = (
    "Paste an access key pair from an AWS identity your team already manages."
)

# Fallback for a source build or a channel without an allowlisted regional S3
# template origin. CloudFormation rejects custom distribution and website hosts.
NO_LINK_RECOVERY_LINE = (
    "Reinstall from a hosted Yoke release, or go back and use existing credentials."
)


def hosting_provider_body() -> list[Static]:
    """The provider-level truth: AWS, self-hosted, or undecided."""
    return [
        Static(HOSTING_PROVIDER_TITLE, classes="onboard-title"),
        Static(HOSTING_PROVIDER_SUBTITLE, classes="onboard-subtitle"),
        Static("", classes="onboard-spacer"),
        SelectionList(HOSTING_PROVIDER_ROWS),
    ]


def hosting_aws_sign_in_body() -> list[Static]:
    """The AWS-only choice between guided, existing, and deferred access."""
    return [
        Static(HOSTING_AWS_SIGN_IN_TITLE, classes="onboard-title"),
        Static(HOSTING_AWS_SIGN_IN_SUBTITLE, classes="onboard-subtitle"),
        Static("", classes="onboard-spacer"),
        SelectionList(HOSTING_AWS_SIGN_IN_ROWS),
    ]


def hosting_guided_key_body(
    *,
    quick_create_url: str | None,
    credential_dir: str,
) -> list[Static]:
    """Credential entry with the one-click dedicated-key route."""
    setup_line = quick_create_url or NO_LINK_RECOVERY_LINE
    return _hosting_credential_body(
        title=HOSTING_GUIDED_KEY_TITLE,
        subtitle=HOSTING_GUIDED_KEY_SUBTITLE,
        credential_dir=credential_dir,
        creation_link=setup_line,
    )


def hosting_existing_key_body(*, credential_dir: str) -> list[Static]:
    """Credential entry for an access key the operator already manages."""
    return _hosting_credential_body(
        title=HOSTING_EXISTING_KEY_TITLE,
        subtitle=HOSTING_EXISTING_KEY_SUBTITLE,
        credential_dir=credential_dir,
        creation_link=None,
    )


def _hosting_credential_body(
    *,
    title: str,
    subtitle: str,
    credential_dir: str,
    creation_link: str | None,
) -> list[Static]:
    widgets: list[Static] = [
        Static(title, classes="onboard-title"),
        Static(subtitle, classes="onboard-subtitle"),
        Static("", classes="onboard-spacer"),
    ]
    if creation_link is not None:
        widgets.extend([
            Static(
                "  1  Set up the dedicated AWS key:",
                classes="onboard-plan-line",
            ),
            Static(
                f"     [{ACCENT}]{escape(creation_link)}[/]",
                classes="onboard-plan-line",
            ),
            Static("", classes="onboard-spacer"),
            Static(
                "  2  Paste the two values here — never into an AI chat:",
                classes="onboard-plan-line",
            ),
        ])
    else:
        widgets.append(Static(
            "  Paste the two values here — never into an AI chat:",
            classes="onboard-plan-line",
        ))
    widgets.extend([
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
        SelectionList(HOSTING_CREDENTIAL_ROWS),
    ])
    return widgets


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
            f"[{ACCENT}]✔ AWS identity verified · aws-admin saved[/]",
            classes="onboard-title",
        ),
        Static("", classes="onboard-spacer"),
        Static(f"  Account       {escape(account)}", classes="onboard-plan-line"),
        Static(f"  Identity      {escape(identity)}", classes="onboard-plan-line"),
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
    "HOSTING_AWS_SIGN_IN_ROWS",
    "HOSTING_AWS_SIGN_IN_SUBTITLE",
    "HOSTING_AWS_SIGN_IN_TITLE",
    "HOSTING_CREDENTIAL_FIELDS",
    "HOSTING_CREDENTIAL_ROWS",
    "HOSTING_EXISTING_KEY_SUBTITLE",
    "HOSTING_EXISTING_KEY_TITLE",
    "HOSTING_GUIDED_KEY_SUBTITLE",
    "HOSTING_GUIDED_KEY_TITLE",
    "HOSTING_NO_MANAGED_HOST_FIELDS",
    "HOSTING_NO_MANAGED_HOST_ROWS",
    "HOSTING_NO_MANAGED_HOST_TITLE",
    "HOSTING_PREREQUISITE_ROWS",
    "HOSTING_PREREQUISITE_TITLE",
    "HOSTING_PROVIDER_NOTE_FIELD",
    "HOSTING_PROVIDER_ROWS",
    "HOSTING_PROVIDER_SUBTITLE",
    "HOSTING_PROVIDER_TITLE",
    "HOSTING_RETRY_ROWS",
    "HOSTING_SECRET_KEY_FIELD",
    "HOSTING_VERIFIED_ROWS",
    "NO_LINK_RECOVERY_LINE",
    "hosting_aws_sign_in_body",
    "hosting_error_body",
    "hosting_existing_key_body",
    "hosting_guided_key_body",
    "hosting_no_managed_host_body",
    "hosting_provider_body",
    "hosting_verified_body",
]
