"""Missing approval tabs expose sign-in prerequisites without leaking codes."""

import pytest

from yoke_harness import identity_browser_approval as driver
from yoke_contracts.machine_browser_approval import missing_approval_tab

ORIGIN = "https://app.example"
CODE = "K7F2"
ENTRY = f"{ORIGIN}/connect?user_code={CODE}"
REAUTHORIZE = "yoke browser authorize --project acme --identity operator --test-machine lab"


@pytest.mark.parametrize("path", ["/auth/sign-in", "/beta", "/orgs/new", "/orgs/new/"])
def test_app_sign_in_routes_name_prerequisite_and_strip_parameters(path):
    result = missing_approval_tab(
        browser="Chromium",
        expected_origin=ORIGIN,
        user_code=CODE,
        observed=[ORIGIN + path + f"?return_to=/connect?user_code={CODE}#private"],
        reauthorize_command=REAUTHORIZE,
    )
    assert result.error_code == "machine_browser_sign_in_required"
    assert result.evidence["observed_tab_paths"] == [path]
    assert f"`{REAUTHORIZE}`" in result.evidence["recovery"]
    assert "Never sign in inside this window" in result.evidence["recovery"]
    assert CODE not in str(result.evidence)
    assert "private" not in str(result.evidence)


def test_external_tab_stays_missing_and_redacts_path_code():
    result = missing_approval_tab(
        browser="Chromium",
        expected_origin=ORIGIN,
        user_code=CODE,
        observed=[f"https://identity.example/auth/{CODE}?secret=private"],
        reauthorize_command=REAUTHORIZE,
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
        reauthorize_command=REAUTHORIZE,
    )
    assert result.error_code == "machine_browser_sign_in_required"
    assert REAUTHORIZE in result.evidence["recovery"]
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
        reauthorize_command=REAUTHORIZE,
    )
    assert result.error_code == "machine_browser_tab_missing"
    assert "fresh request" in result.evidence["recovery"]


def test_the_driver_names_the_reauthorize_command_for_an_expired_login(monkeypatch):
    observed = ORIGIN + "/auth/sign-in?return_to=" + CODE
    monkeypatch.setattr(driver.identity_browser_devtools, "TAB_WAIT_SECONDS", 0)
    monkeypatch.setattr(
        driver,
        "_host",
        lambda *args, **kwargs: {"ok": True, "urls": [observed], "identity_browsers": 1},
    )
    result = driver.approve_machine_in_identity_browser(
        lambda *a, **k: None,
        verification_url=ENTRY,
        user_code=CODE,
        reauthorize_command=REAUTHORIZE,
        yoke_bin="yoke",
    )
    assert result.error_code == "machine_browser_sign_in_required"
    assert result.evidence["observed_tab_paths"] == ["/auth/sign-in"]
    assert REAUTHORIZE in result.evidence["recovery"]


def test_no_running_identity_browser_says_the_link_bypassed_the_launcher(monkeypatch):
    monkeypatch.setattr(driver.identity_browser_devtools, "TAB_WAIT_SECONDS", 0)
    monkeypatch.setattr(
        driver,
        "_host",
        lambda *args, **kwargs: {"ok": True, "urls": [], "identity_browsers": 0},
    )
    result = driver.approve_machine_in_identity_browser(
        lambda *a, **k: None,
        verification_url=ENTRY,
        user_code=CODE,
        reauthorize_command=REAUTHORIZE,
        yoke_bin="yoke",
    )
    assert result.error_code == "machine_browser_tab_missing"
    assert result.evidence["state"] == "identity_browser_not_running"
    assert "yoke browser open" in result.evidence["recovery"]


def test_observed_other_request_codes_are_redacted():
    result = missing_approval_tab(
        browser="Chromium",
        expected_origin=ORIGIN,
        user_code=CODE,
        observed=[ORIGIN + "/orgs/acme/machine-approval/Z9A2?selection=all"],
        reauthorize_command=REAUTHORIZE,
    )
    assert result.evidence["observed_tab_paths"] == [
        "/orgs/acme/machine-approval/[REDACTED]"
    ]
