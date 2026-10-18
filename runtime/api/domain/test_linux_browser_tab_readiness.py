"""An existing same-origin tab does not prove this request's tab is ready."""

import json

import pytest

from yoke_harness import ssh_linux_browser_approval as driver

START = "https://app.example/connect?user_code=AB12-CD34"
ROUTE = "https://app.example/orgs/acme/machine-approval/AB12-CD34"


def _clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(driver.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(
        driver.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds)
    )
    return now


@pytest.mark.parametrize("target", [START, ROUTE + "?selection=1,2"])
def test_waits_for_exact_request_after_an_existing_origin_tab(monkeypatch, target):
    _clock(monkeypatch)
    observed = iter([["https://app.example/"], ["https://app.example/", target]])
    calls = []

    def host(control, command, *args):
        calls.append(command)
        if command == "tabs":
            return {"ok": True, "urls": next(observed)}
        assert target in json.loads(args[0])
        return {
            "ok": True,
            "state": "approved",
            "starting_url": target,
            "result_url": "https://app.example/orgs/acme/frontier",
        }

    monkeypatch.setattr(driver, "_host", host)
    result = driver.approve_machine_in_desktop_chromium(
        object(), verification_url=START, user_code="AB12-CD34"
    )
    assert result.ok
    assert calls == ["tabs", "tabs", "approve"]


def test_unrelated_or_wrong_code_tabs_time_out_without_pressing(monkeypatch):
    now = _clock(monkeypatch)
    monkeypatch.setattr(driver.linux_desktop_chromium, "TAB_WAIT_SECONDS", 1)

    def host(control, command, *args):
        assert command == "tabs"
        return {
            "ok": True,
            "urls": ["https://app.example/", ROUTE.replace("AB12", "ZZ99")],
        }

    monkeypatch.setattr(driver, "_host", host)
    result = driver.approve_machine_in_desktop_chromium(
        object(), verification_url=START, user_code="AB12-CD34"
    )
    assert not result.ok
    assert result.error_code == "machine_browser_tab_missing"
    assert "fresh request" in result.evidence["recovery"]
    assert now[0] == 1


def test_tab_reader_refusal_is_preserved_without_retry(monkeypatch):
    _clock(monkeypatch)
    calls = []

    def host(control, command, *args):
        calls.append(command)
        return {
            "ok": False,
            "reason": "devtools_unavailable",
            "recovery": "repair desktop",
        }

    monkeypatch.setattr(driver, "_host", host)
    result = driver.approve_machine_in_desktop_chromium(
        object(), verification_url=START, user_code="AB12-CD34"
    )
    assert not result.ok
    assert result.evidence["reason"] == "devtools_unavailable"
    assert calls == ["tabs"]
