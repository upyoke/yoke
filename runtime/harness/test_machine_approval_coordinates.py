"""Complete verification links retain strict code and entry-path binding."""

import json

import pytest
from subprocess import CompletedProcess

from yoke_contracts.machine_approval_coordinates import machine_approval_coordinates
from yoke_harness import ssh_linux_browser_approval as chromium
from yoke_harness import ssh_mac_browser_approval as safari
from yoke_harness.machine_browser_approval import approval_tab_urls, approval_url


@pytest.mark.parametrize("path", ["/connect", "/machine"])
def test_base_and_complete_uris_resolve_to_the_same_exact_request(path):
    base = "https://example.invalid" + path
    complete = base + "?user_code=AB12-CD34"
    assert machine_approval_coordinates(
        base, "AB12-CD34"
    ) == machine_approval_coordinates(complete, "AB12-CD34")
    assert approval_url(complete, "AB12-CD34") == (complete, "https://example.invalid")


def test_self_hosted_code_path_is_preserved_for_the_wizard_opened_tab():
    complete = "https://example.invalid/machine/AB12-CD34"
    assert approval_url(complete, "AB12-CD34")[0] == complete


@pytest.mark.parametrize(
    "uri",
    [
        "http://example.invalid/connect",
        "https://user:password@example.invalid/connect",
        "https://example.invalid/anything",
        "https://example.invalid/connect#fragment",
        "https://example.invalid/connect?user_code=EF56-GH78",
        "https://example.invalid/connect?user_code=AB12-CD34&user_code=AB12-CD34",
        "https://example.invalid/connect?other=AB12-CD34",
        "https://example.invalid/connect?user_code=AB12-CD34&other=value",
        "https://example.invalid/connect?user_code",
        "https://example.invalid/machine/EF56-GH78",
    ],
)
def test_unrelated_or_ambiguous_coordinates_cannot_be_approved(uri):
    with pytest.raises(ValueError):
        machine_approval_coordinates(uri, "AB12-CD34")


ENTRY = "https://example.invalid/connect?user_code=AB12-CD34"
REDIRECT = "https://example.invalid/orgs/example/machine-approval/AB12-CD34"
DESTINATION = "https://example.invalid/orgs/example/strategy?status=approved"


def test_redirect_keeps_the_exact_origin_code_and_single_organization_segment():
    assert approval_tab_urls(ENTRY, "AB12-CD34", [REDIRECT, REDIRECT]) == [
        ENTRY,
        REDIRECT,
    ]


@pytest.mark.parametrize(
    "url",
    [
        "https://other.invalid/orgs/example/machine-approval/AB12-CD34",
        "http://example.invalid/orgs/example/machine-approval/AB12-CD34",
        "https://user@example.invalid/orgs/example/machine-approval/AB12-CD34",
        "https://example.invalid/orgs/example/machine-approval/EF56-GH78",
        "https://example.invalid/orgs//machine-approval/AB12-CD34",
        "https://example.invalid/orgs/../machine-approval/AB12-CD34",
        "https://example.invalid/orgs/%2e%2e/machine-approval/AB12-CD34",
        "https://example.invalid/orgs/example/other/machine-approval/AB12-CD34",
        REDIRECT + "/",
        REDIRECT + "?user_code=AB12-CD34",
        REDIRECT + "#fragment",
        "https://[invalid",
    ],
)
def test_redirect_tab_rejects_ambiguous_or_unrelated_requests(url):
    assert approval_tab_urls(ENTRY, "AB12-CD34", [url]) == [ENTRY]


def test_machine_entry_does_not_authorize_the_hosted_redirect_route():
    entry = "https://example.invalid/machine/AB12-CD34"
    assert approval_tab_urls(entry, "AB12-CD34", [REDIRECT]) == [entry]


def _safari(monkeypatch, *, response, observed):
    scripts = []
    results = iter(
        [
            CompletedProcess([], 0, observed + "\n", ""),
            CompletedProcess([], 0, response, ""),
        ]
    )

    def run_script(_run, script):
        scripts.append(script)
        return next(results)

    monkeypatch.setattr(safari, "run_osascript", run_script)
    outcome = safari.approve_machine_in_safari(
        lambda *_args, **_kwargs: None,
        verification_url=ENTRY,
        user_code="AB12-CD34",
    )
    return outcome, scripts


def _chromium(monkeypatch, *, response, observed):
    calls = []

    def host(_control, command, *arguments, desktop=True):
        calls.append((command, *arguments))
        if command == "tabs":
            return {"ok": True, "urls": [observed]}
        state, _, navigation = response.partition("|")
        starting_url, _, result_url = navigation.partition("|")
        return {
            "ok": True,
            "state": state,
            "starting_url": starting_url,
            "result_url": result_url,
        }

    monkeypatch.setattr(chromium, "_host", host)
    outcome = chromium.approve_machine_in_desktop_chromium(
        object(), verification_url=ENTRY, user_code="AB12-CD34"
    )
    return outcome, calls


#: Every native browser driver shares one matcher and outcome contract.
DRIVERS = {"Safari": _safari, "Chromium": _chromium}


@pytest.fixture(params=sorted(DRIVERS))
def driver(request):
    return request.param


def _approval(monkeypatch, driver, *, response, observed=REDIRECT):
    return DRIVERS[driver](monkeypatch, response=response, observed=observed)


@pytest.mark.parametrize("starting_url", [ENTRY, REDIRECT])
def test_approval_requires_navigation_from_the_tab_that_was_actually_matched(
    monkeypatch,
    driver,
    starting_url,
):
    outcome, _ = _approval(
        monkeypatch,
        driver,
        response=f"approved|{starting_url}|{DESTINATION}",
        observed=starting_url,
    )
    assert outcome.ok
    assert outcome.evidence == {
        "browser": driver,
        "approval_entry": starting_url.split("?")[0].removeprefix(
            "https://example.invalid"
        ),
        "result_url": DESTINATION.split("?")[0],
        "visible_control": "Approve machine",
    }


def test_safari_revalidates_the_matched_tab_before_reporting_navigation(monkeypatch):
    _, scripts = _approval(
        monkeypatch, "Safari", response=f"approved|{ENTRY}|{DESTINATION}"
    )
    approval_script = "\n".join(scripts[1])
    assert "set matchedStartingURL to tabURL" in approval_script
    assert "resultURL is not matchedStartingURL" in approval_script
    assert "resultURL is not expectedURL" not in approval_script


def test_chromium_presses_only_in_the_allowed_tabs(monkeypatch):
    _, calls = _approval(
        monkeypatch, "Chromium", response=f"approved|{REDIRECT}|{DESTINATION}"
    )
    assert calls == [
        ("tabs", "https://example.invalid"),
        (
            "approve",
            json.dumps([ENTRY, REDIRECT]),
            "Approve machine",
        ),
    ]


@pytest.mark.parametrize(
    "response",
    [
        f"approved|{REDIRECT}|{REDIRECT}",
        f"approved|{ENTRY}|{ENTRY}",
        f"approved|https://other.invalid/connect|{DESTINATION}",
        f"approved|{REDIRECT.replace('AB12-CD34', 'EF56-GH78')}|{DESTINATION}",
        f"approved|{DESTINATION}",
        "browser_tab_changed",
    ],
)
def test_unchanged_redirect_or_unmatched_start_cannot_be_reported_as_approved(
    monkeypatch,
    driver,
    response,
):
    outcome, _ = _approval(monkeypatch, driver, response=response)
    assert not outcome.ok


@pytest.mark.parametrize(
    "destination",
    [
        "https://other.invalid/success",
        "https://example.invalid/connect?status=denied",
        "https://example.invalid/connect?status=expired",
    ],
)
def test_clicked_approval_still_rejects_foreign_or_refused_destinations(
    monkeypatch,
    driver,
    destination,
):
    outcome, _ = _approval(
        monkeypatch,
        driver,
        response=f"approved|{REDIRECT}|{destination}",
    )
    assert outcome.error_code == "machine_browser_approval_destination_invalid"


@pytest.mark.parametrize(
    ("verification_url", "user_code"),
    (
        ("http://example.invalid/connect", "AB12-CD34"),
        ("https://example.invalid/anything", "AB12-CD34"),
        ("https://example.invalid/connect?other=1", "AB12-CD34"),
        ("https://example.invalid/connect", "bad-code"),
    ),
)
def test_invalid_context_never_reaches_the_browser(
    monkeypatch, driver, verification_url, user_code
):
    touched = []
    monkeypatch.setattr(safari, "run_osascript", lambda *a: touched.append(a))
    monkeypatch.setattr(chromium, "_host", lambda *a, **k: touched.append(a))
    approve = {
        "Safari": lambda: safari.approve_machine_in_safari(
            lambda *_a, **_k: None,
            verification_url=verification_url,
            user_code=user_code,
        ),
        "Chromium": lambda: chromium.approve_machine_in_desktop_chromium(
            object(), verification_url=verification_url, user_code=user_code
        ),
    }[driver]
    result = approve()
    assert result.ok is False
    assert result.error_code == "machine_browser_context_invalid"
    assert touched == []


@pytest.mark.parametrize(
    ("response", "error_code"),
    (
        ("browser_tab_missing", "machine_browser_tab_missing"),
        ("browser_tab_changed", "machine_browser_tab_changed"),
        ("approval_control_missing", "machine_browser_approval_control_missing"),
        ("approval_navigation_missing", "machine_browser_approval_navigation_missing"),
        (
            f"approved|{ENTRY}|https://evil.example/orgs/acme",
            "machine_browser_approval_destination_invalid",
        ),
        (
            f"approved|{ENTRY}|https://example.invalid/connect?status=denied",
            "machine_browser_approval_destination_invalid",
        ),
    ),
)
def test_automation_refuses_missing_or_untrusted_browser_outcomes(
    monkeypatch, driver, response, error_code
):
    outcome, _ = _approval(monkeypatch, driver, response=response, observed=ENTRY)
    assert outcome.ok is False
    assert outcome.error_code == error_code
    assert outcome.evidence["browser"] == driver


@pytest.mark.parametrize("query", ["?selection=all", "?selection=1,4"])
def test_dashboard_selection_redirect_is_approved_by_every_driver(
    monkeypatch, driver, query
):
    starting_url = REDIRECT + query
    outcome, _ = _approval(
        monkeypatch,
        driver,
        response=f"approved|{starting_url}|{DESTINATION}",
        observed=starting_url,
    )
    assert outcome.ok, outcome.evidence


@pytest.mark.parametrize(
    "query", ["?selection=1,1", "?selection=all&other=1", "?other=1"]
)
def test_noncanonical_selection_redirect_is_never_pressed(monkeypatch, driver, query):
    starting_url = REDIRECT + query
    outcome, _ = _approval(
        monkeypatch,
        driver,
        response=f"approved|{starting_url}|{DESTINATION}",
        observed=starting_url,
    )
    assert outcome.error_code == "machine_browser_approval_navigation_missing"
