"""Google's account chooser is passed with the declared account, never a password."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.browser_identity import parse_identity_declarations
from yoke_core.domain import machine_approval_accounts as accounts_module
from yoke_harness import ssh_linux_browser_approval as linux
from yoke_harness.machine_account_chooser import (
    DeclaredAccounts,
    account_chooser_url,
    declared_accounts,
)
from yoke_harness.ssh_mac_browser_approval import approve_machine_in_safari

ORIGIN = "https://app.upyoke.com"
CODE = "K7F2"
ENTRY = f"{ORIGIN}/connect?user_code={CODE}"
APPROVAL = f"{ORIGIN}/orgs/upyoke/machine-approval/{CODE}"
# Recorded from hosted sign-in: the app asks Google with prompt=select_account.
CHOOSER = (
    "https://accounts.google.com/v3/signin/accountchooser?client_id=945970311197"
    "-49u5aq09uv3p8du70n3q5es0m42m8shn.apps.googleusercontent.com&dsh=S1&o2v=2"
    "&prompt=select_account&redirect_uri=https%3A%2F%2Fapp.upyoke.com%2Fauth"
    "%2Fcallback&response_type=code&scope=openid+email+profile&service=lso"
    "&flowName=GeneralOAuthFlow"
)
# The visible text Safari's accessibility tree reports for that chooser.
CHOOSER_TEXT = [
    "Choose an account",
    "to continue to upyoke.com",
    "Testy Upyoke",
    "testy@upyoke.com",
    "Someone Else",
    "someone@example.com",
    "Use another account",
]
PASSWORD_PAGE = (
    "https://accounts.google.com/v3/signin/challenge/pwd?TL=secret-token&cid=1"
)
DECLARED = DeclaredAccounts({ORIGIN: ("testy@upyoke.com",)})


class SafariRecording:
    """A Safari that shows the recorded chooser and records every script."""

    def __init__(self, *, after_pick: str, offered=CHOOSER_TEXT):
        self.tabs = [CHOOSER]
        self.after_pick = after_pick
        self.offered = offered
        self.scripts: list[str] = []

    def __call__(self, command: str, **_kwargs) -> subprocess.CompletedProcess:
        self.scripts.append(command)
        if "set tabURLs" in command:
            out = "".join(url + "\n" for url in self.tabs)
        elif "set offered to" in command:
            out = "offered\n" + "\n".join(t for t in self.offered if "@" in t)
        elif "set accountName" in command:
            self.tabs = [self.after_pick]
            state = (
                "arrived"
                if self.after_pick.startswith(ORIGIN)
                else "choice_unconfirmed"
            )
            out = f"{state}|{self.after_pick}"
        elif "set allowedURLs" in command:
            out = f"approved_in_place|{APPROVAL}|{APPROVAL}"
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess([], 0, out, "")


def _safari(recording, declared=DECLARED):
    return approve_machine_in_safari(
        recording,
        verification_url=ENTRY,
        user_code=CODE,
        declared_accounts=declared,
    )


def test_safari_picks_the_declared_account_and_reaches_approval():
    recording = SafariRecording(after_pick=APPROVAL)
    result = _safari(recording)
    assert result.ok, result.evidence
    assert result.evidence["account_chooser"] == {
        "account": "testy@upyoke.com",
        "arrived_path": "/orgs/upyoke/machine-approval/[REDACTED]",
    }
    assert result.evidence["visible_confirmation"] == "Machine connected"
    press = next(s for s in recording.scripts if "set accountName" in s)
    assert '"testy@upyoke.com"' in press and "someone@example.com" not in press
    assert not any("keystroke" in script for script in recording.scripts)


def test_safari_stops_at_a_password_page_for_the_operator():
    recording = SafariRecording(after_pick=PASSWORD_PAGE)
    result = _safari(recording)
    assert result.error_code == "machine_browser_sign_in_required"
    assert result.evidence["state"] == "identity_provider_step"
    assert result.evidence["observed_path"] == "/v3/signin/challenge/pwd"
    assert "secret-token" not in str(result.evidence)
    assert "operator completes" in result.evidence["recovery"]
    assert not any("set allowedURLs" in script for script in recording.scripts)
    assert not any("keystroke" in script for script in recording.scripts)


@pytest.mark.parametrize(
    ("declared", "offered", "code", "state"),
    [
        (
            DECLARED,
            ["other@example.com"],
            "machine_browser_sign_in_required",
            "account_not_offered",
        ),
        (
            DeclaredAccounts({ORIGIN: ("testy@upyoke.com", "someone@example.com")}),
            CHOOSER_TEXT,
            "machine_browser_account_ambiguous",
            "account_ambiguous",
        ),
        (
            DeclaredAccounts(),
            CHOOSER_TEXT,
            "machine_browser_sign_in_required",
            "account_chooser",
        ),
    ],
)
def test_safari_never_guesses_an_account(declared, offered, code, state):
    recording = SafariRecording(after_pick=APPROVAL, offered=offered)
    result = _safari(recording, declared)
    assert (result.error_code, result.evidence["state"]) == (code, state)
    assert not any("set accountName" in script for script in recording.scripts)


def test_unreadable_declarations_name_their_reason():
    declared = DeclaredAccounts(
        unavailable="browser_identity_declarations_unreadable: down"
    )
    result = _safari(SafariRecording(after_pick=APPROVAL), declared)
    assert result.evidence["declarations"] == declared.unavailable


def test_only_a_chooser_returning_to_the_approval_origin_qualifies():
    assert account_chooser_url(["https://example.com/x", CHOOSER], ORIGIN) == CHOOSER
    assert account_chooser_url([CHOOSER], "https://app.upyoke.com.evil") is None
    assert (
        account_chooser_url([CHOOSER.replace("accountchooser", "identifier")], ORIGIN)
        is None
    )


def test_linux_picks_the_declared_account_through_devtools(monkeypatch):
    calls = []
    tabs = iter([[CHOOSER], [APPROVAL]])

    def host(_control, command, *arguments, **_kwargs):
        calls.append((command, *arguments))
        if command == "tabs":
            return {"ok": True, "urls": next(tabs)}
        if command == "chooser-accounts":
            return {"ok": True, "state": "offered", "accounts": ["testy@upyoke.com"]}
        if command == "choose":
            return {"ok": True, "state": "arrived", "result_url": APPROVAL}
        return {
            "ok": True,
            "state": "approved_in_place",
            "starting_url": APPROVAL,
            "result_url": APPROVAL,
        }

    monkeypatch.setattr(linux, "_host", host)
    result = linux.approve_machine_in_desktop_chromium(
        object(), verification_url=ENTRY, user_code=CODE, declared_accounts=DECLARED
    )
    assert result.ok, result.evidence
    assert result.evidence["account_chooser"]["account"] == "testy@upyoke.com"
    assert ("choose", CHOOSER, "testy@upyoke.com", ORIGIN, "30") in calls


def test_declared_accounts_group_identity_sites_by_origin():
    identities = parse_identity_declarations(
        {
            "identities": {
                name: {
                    "sites": [
                        {
                            "site": "prod",
                            "origin": ORIGIN,
                            "account": account,
                            "probe": {
                                "url": ORIGIN + "/auth/sign-in",
                                "signed_in_status": 303,
                            },
                        }
                    ]
                }
                for name, account in (
                    ("admin", "ben@upyoke.com"),
                    ("operator", "testy@upyoke.com"),
                )
            }
        }
    )
    assert declared_accounts(identities).for_origin(ORIGIN + "/") == (
        "ben@upyoke.com",
        "testy@upyoke.com",
    )


def test_declarations_are_read_only_for_browser_approval_cases(monkeypatch):
    replies = []

    def call(**kwargs):
        replies.append(kwargs["payload"])
        settings = {
            "identities": {
                "operator": {
                    "sites": [
                        {
                            "site": "prod",
                            "origin": ORIGIN,
                            "account": "testy@upyoke.com",
                            "probe": {
                                "url": ORIGIN + "/auth/sign-in",
                                "signed_in_status": 303,
                            },
                        }
                    ]
                }
            }
        }
        return SimpleNamespace(
            success=True, error=None, result={"settings_json": json.dumps(settings)}
        )

    monkeypatch.setattr("yoke_core.domain.qa_composed_dispatch.call_qa_function", call)
    nested = {
        "baseline_configs": {
            "fresh-host": {"actions": [{"operator_gate": "machine_browser_approval"}]}
        }
    }
    assert (
        accounts_module.case_declared_accounts("yoke", [{"actions": []}])
        == DeclaredAccounts()
    )
    assert replies == []
    assert accounts_module.case_declared_accounts("yoke", [nested]).for_origin(
        ORIGIN
    ) == ("testy@upyoke.com",)
    assert replies == [{"project": "yoke", "cap_type": "browser-control"}]


def test_a_failed_declaration_read_is_named_not_guessed(monkeypatch):
    failure = SimpleNamespace(code="unavailable", message="control plane down")
    monkeypatch.setattr(
        "yoke_core.domain.qa_composed_dispatch.call_qa_function",
        lambda **_kw: SimpleNamespace(success=False, error=failure, result=None),
    )
    declared = accounts_module.read_declared_accounts("yoke")
    assert declared.by_origin == {}
    assert declared.unavailable.startswith("browser_identity_declarations_unreadable")
