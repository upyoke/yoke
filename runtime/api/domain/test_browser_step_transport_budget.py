"""A step's declared budget has to survive the transport carrying it.

The daemon call had one fixed timeout, shorter than the waits a case
against real rows needs. A step declaring sixty seconds could therefore
never report what it found: the transport stopped listening at thirty and
the case recorded "JSON request exceeded its time limit" in place of the
step's own verdict. These pin that the request outlives the step it
carries, and that an ordinary step still uses the ordinary timeout.
"""

from __future__ import annotations

from yoke_core.domain import browser_client


def _timeout_for(step, monkeypatch) -> int:
    seen: dict[str, int] = {}

    def _capture(path, body=None, timeout=browser_client.DEFAULT_DAEMON_REQUEST_TIMEOUT_SECONDS, **_):
        seen["path"] = path
        seen["timeout"] = timeout
        return {"success": True}

    monkeypatch.setattr(browser_client, "daemon_request", _capture)
    browser_client.execute_step(step, "http://127.0.0.1:1/")
    assert seen["path"] == "/api/exec/step"
    return seen["timeout"]


def test_a_step_without_its_own_budget_uses_the_ordinary_timeout(monkeypatch):
    timeout = _timeout_for({"action": "delay", "ms": 1}, monkeypatch)
    assert timeout == browser_client.DEFAULT_DAEMON_REQUEST_TIMEOUT_SECONDS


def test_a_long_wait_outlives_the_transport_default(monkeypatch):
    """The failure this prevents: a sixty-second wait against real rows
    reported a request timeout at thirty instead of its own answer."""
    timeout = _timeout_for(
        {"action": "assert", "check": "visible", "target": ".card",
         "timeout_ms": 60000},
        monkeypatch,
    )
    assert timeout == 60 + browser_client.STEP_RESPONSE_HEADROOM_SECONDS
    assert timeout > browser_client.DEFAULT_DAEMON_REQUEST_TIMEOUT_SECONDS


def test_a_short_wait_never_shortens_the_transport(monkeypatch):
    """A step may ask for less time than the transport already allows; it
    must not take time away from the response that follows it."""
    timeout = _timeout_for(
        {"action": "assert", "check": "visible", "target": ".card",
         "timeout_ms": 2000},
        monkeypatch,
    )
    assert timeout == browser_client.DEFAULT_DAEMON_REQUEST_TIMEOUT_SECONDS


def test_a_nonsense_budget_is_ignored_rather_than_obeyed(monkeypatch):
    for declared in (0, -1, "60000", None):
        timeout = _timeout_for(
            {"action": "delay", "ms": 1, "timeout_ms": declared}, monkeypatch,
        )
        assert timeout == browser_client.DEFAULT_DAEMON_REQUEST_TIMEOUT_SECONDS
