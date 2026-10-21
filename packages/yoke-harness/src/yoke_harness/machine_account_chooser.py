"""Pick the project's declared account in Google's account chooser.

Hosted sign-in asks Google with ``prompt=select_account``, so a browser that
lost its app session but kept its Google session stops at Google's account
chooser on the way to the approval page. The chooser asks for no secret, so a
driver may pick an account there. This contract decides which chooser tab
qualifies, which account to pick and what each driver outcome means; drivers
own only how they read and press the page. A driver never types a password: a
password, 2-Step or consent page after the pick goes to the operator as
``machine_browser_sign_in_required``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from urllib.parse import unquote, urlsplit

from yoke_contracts.browser_identity import BrowserIdentity
from yoke_harness.machine_browser_approval import (
    SIGN_IN_RECOVERY,
    BrowserApprovalResult,
    redacted_path,
)


GOOGLE_HOST = "accounts.google.com"
ACCOUNT_CHOOSER_PATHS = frozenset(
    {
        "/v3/signin/accountchooser",
        "/o/oauth2/auth/oauthchooseaccount",
        "/signin/oauth/oauthchooseaccount",
    }
)
#: How long a driver waits after the pick for the tab to settle on the origin.
CHOOSER_WAIT_SECONDS = 30
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CHOOSER_STATES = {
    "chooser_tab_changed": "machine_browser_tab_changed",
    "account_control_missing": "machine_browser_account_control_missing",
}


@dataclass(frozen=True)
class DeclaredAccounts:
    """Accounts the project's browser identities declare, keyed by site origin.

    ``unavailable`` names why the declarations could not be read; a chooser
    then refuses with that reason instead of guessing an account.
    """

    by_origin: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    unavailable: str | None = None

    def for_origin(self, origin: str) -> tuple[str, ...]:
        return self.by_origin.get(origin.rstrip("/"), ())


def declared_accounts(identities: Mapping[str, BrowserIdentity]) -> DeclaredAccounts:
    """Collect every declared site account, once per origin."""
    by_origin: dict[str, list[str]] = {}
    for identity in identities.values():
        for site in identity.sites:
            accounts = by_origin.setdefault(site.origin.rstrip("/"), [])
            if site.account and site.account.casefold() not in {
                account.casefold() for account in accounts
            }:
                accounts.append(site.account)
    return DeclaredAccounts(
        {origin: tuple(accounts) for origin, accounts in by_origin.items() if accounts}
    )


def _returns_to(url: str, origin: str) -> bool:
    text = url
    for _ in range(4):
        if f"redirect_uri={origin}/" in text:
            return True
        decoded = unquote(text)
        if decoded == text:
            return False
        text = decoded
    return False


def account_chooser_url(observed: Sequence[str], expected_origin: str) -> str | None:
    """Return the Google account chooser tab whose sign-in returns to the origin."""
    for value in observed:
        try:
            parsed = urlsplit(value)
        except ValueError:
            continue
        if (
            parsed.scheme == "https"
            and parsed.hostname == GOOGLE_HOST
            and parsed.path.rstrip("/") in ACCOUNT_CHOOSER_PATHS
            and _returns_to(value, expected_origin)
        ):
            return value
    return None


def _sign_in_required(
    browser: str, state: str, **evidence: object
) -> BrowserApprovalResult:
    return BrowserApprovalResult(
        False,
        {"browser": browser, "state": state, **evidence, "recovery": SIGN_IN_RECOVERY},
        "machine_browser_sign_in_required",
    )


def pick_account(
    *,
    browser: str,
    expected_origin: str,
    offered: Sequence[str],
    declared: DeclaredAccounts,
) -> tuple[str | None, BrowserApprovalResult | None]:
    """Choose the one declared account the chooser offers, or refuse."""
    accounts = declared.for_origin(expected_origin)
    if not accounts:
        return None, _sign_in_required(
            browser,
            "account_chooser",
            declared_accounts=[],
            declarations=declared.unavailable
            or f"no browser identity declares an account for {expected_origin}",
        )
    wanted = {account.casefold(): account for account in accounts}
    listed = [value.strip() for value in offered if _EMAIL.match(value.strip())]
    matches = sorted({wanted[v.casefold()] for v in listed if v.casefold() in wanted})
    if not matches:
        return None, _sign_in_required(
            browser,
            "account_not_offered",
            declared_accounts=list(accounts),
            offered_account_count=len(set(v.casefold() for v in listed)),
        )
    if len(matches) > 1:
        return None, BrowserApprovalResult(
            False,
            {
                "browser": browser,
                "state": "account_ambiguous",
                "offered_declared_accounts": matches,
                "recovery": (
                    "Google's account chooser offers more than one account the "
                    f"project declares for {expected_origin}. Sign all but the "
                    "approving account out of Google in the Test Machine's "
                    "browser, or remove the extra account from that origin's "
                    "browser identity declarations, then rerun."
                ),
            },
            "machine_browser_account_ambiguous",
        )
    return matches[0], None


def chooser_outcome(
    *,
    browser: str,
    state: str,
    account: str,
    result_url: str,
    expected_origin: str,
) -> BrowserApprovalResult:
    """Accept only a pick that leaves Google and settles on the approval origin."""
    if state in _CHOOSER_STATES:
        return BrowserApprovalResult(
            False,
            {"browser": browser, "state": state, "account": account},
            _CHOOSER_STATES[state],
        )
    try:
        parsed = urlsplit(result_url)
    except ValueError:
        parsed = urlsplit("")
    path = redacted_path(parsed.path or "/")
    if state == "arrived" and f"{parsed.scheme}://{parsed.netloc}" == expected_origin:
        return BrowserApprovalResult(
            True,
            {"account_chooser": {"account": account, "arrived_path": path}},
        )
    if parsed.hostname == GOOGLE_HOST:
        # A password, 2-Step or consent page: only the operator continues.
        return _sign_in_required(
            browser, "identity_provider_step", account=account, observed_path=path
        )
    return BrowserApprovalResult(
        False,
        {
            "browser": browser,
            "state": state or "empty",
            "account": account,
            "observed_path": path if parsed.hostname else None,
            "recovery": (
                "The account pick did not reach the approval origin in "
                f"{CHOOSER_WAIT_SECONDS} seconds. Open the Test Machine's "
                "browser to see where the sign-in stopped, then rerun."
            ),
        },
        "machine_browser_account_choice_unconfirmed",
    )


__all__ = [
    "ACCOUNT_CHOOSER_PATHS",
    "CHOOSER_WAIT_SECONDS",
    "DeclaredAccounts",
    "account_chooser_url",
    "chooser_outcome",
    "declared_accounts",
    "pick_account",
]
