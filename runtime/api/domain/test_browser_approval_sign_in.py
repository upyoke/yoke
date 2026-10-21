"""Missing approval tabs expose sign-in prerequisites without leaking codes."""

import subprocess

import pytest

from yoke_harness import ssh_linux_browser_approval as linux
from yoke_harness import ssh_mac_browser_approval as mac
from yoke_harness.machine_browser_approval import missing_approval_tab
from yoke_harness.machine_account_chooser import DeclaredAccounts

ORIGIN = "https://app.example"
CODE = "K7F2"
ENTRY = f"{ORIGIN}/connect?user_code={CODE}"


@pytest.mark.parametrize("path", ["/auth/sign-in", "/beta", "/orgs/new", "/orgs/new/"])
def test_app_sign_in_routes_name_prerequisite_and_strip_parameters(path):
    result = missing_approval_tab(
        browser="Chromium",
        expected_origin=ORIGIN,
        user_code=CODE,
        observed=[ORIGIN + path + f"?return_to=/connect?user_code={CODE}#private"],
    )
    assert result.error_code == "machine_browser_sign_in_required"
    assert result.evidence["observed_tab_paths"] == [path]
    assert "Keep it live through reset" in result.evidence["recovery"]
    assert CODE not in str(result.evidence)
    assert "private" not in str(result.evidence)


def test_external_tab_stays_missing_and_redacts_path_code():
    result = missing_approval_tab(
        browser="Safari",
        expected_origin=ORIGIN,
        user_code=CODE,
        observed=[f"https://identity.example/auth/{CODE}?secret=private"],
    )
    assert result.error_code == "machine_browser_tab_missing"
    assert result.evidence["observed_tab_paths"] == ["/auth/[REDACTED]"]
    assert "private" not in str(result.evidence)


@pytest.mark.parametrize(
    "url",
    [
        "https://accounts.google.com/v3/signin/accountchooser",
        "https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
    ],
)
def test_identity_provider_sign_in_names_human_prerequisite(url):
    result = missing_approval_tab(
        browser="Chromium",
        expected_origin=ORIGIN,
        user_code=CODE,
        observed=[url + "?code=private"],
    )
    assert result.error_code == "machine_browser_sign_in_required"
    assert "operator completes" in result.evidence["recovery"]
    assert "private" not in str(result.evidence)


@pytest.mark.parametrize(
    "observed",
    [
        [],
        ["chrome://newtab/", "about:blank"],
        [ORIGIN + "/"],
        ["https://evil.example/auth/sign-in"],
        ["https://evil.example/beta"],
        ["https://evil.example/orgs/new"],
    ],
)
def test_absent_approval_without_sign_in_route_stays_missing(observed):
    result = missing_approval_tab(
        browser="Chromium",
        expected_origin=ORIGIN,
        user_code=CODE,
        observed=observed,
    )
    assert result.error_code == "machine_browser_tab_missing"
    assert "fresh request" in result.evidence["recovery"]


@pytest.mark.parametrize("browser", ["Chromium", "Safari"])
def test_drivers_use_shared_missing_tab_classification(monkeypatch, browser):
    observed = ORIGIN + "/auth/sign-in?return_to=" + CODE
    if browser == "Chromium":
        monkeypatch.setattr(linux.linux_desktop_chromium, "TAB_WAIT_SECONDS", 0)
        monkeypatch.setattr(
            linux, "_host", lambda *args: {"ok": True, "urls": [observed]}
        )
        result = linux.approve_machine_in_desktop_chromium(
            object(),
            verification_url=ENTRY,
            user_code=CODE,
            declared_accounts=DeclaredAccounts(),
        )
    else:
        replies = iter([observed, "browser_tab_missing"])
        monkeypatch.setattr(
            mac,
            "run_osascript",
            lambda *a, **kw: subprocess.CompletedProcess([], 0, next(replies), ""),
        )
        result = mac.approve_machine_in_safari(
            lambda *a: None,
            verification_url=ENTRY,
            user_code=CODE,
            declared_accounts=DeclaredAccounts(),
        )
    assert result.error_code == "machine_browser_sign_in_required"
    assert result.evidence["observed_tab_paths"] == ["/auth/sign-in"]


def test_observed_other_request_codes_are_redacted():
    result = missing_approval_tab(
        browser="Chromium",
        expected_origin=ORIGIN,
        user_code=CODE,
        observed=[ORIGIN + "/orgs/acme/machine-approval/Z9A2?selection=all"],
    )
    assert result.evidence["observed_tab_paths"] == [
        "/orgs/acme/machine-approval/[REDACTED]"
    ]
