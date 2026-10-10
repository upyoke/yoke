"""The collector classifies browser, OS and device type from request headers."""

import json

import pytest

from runtime.api.test_frontend_events import client, database, event, headers  # noqa: F401
from yoke_core.frontend_events.events_device import device_props

MAC_CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
)
IPAD = (
    "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)
ANDROID_REDUCED = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
CLAUDE_DESKTOP = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Claude/1.0.211 Chrome/138.0.7204.251 Electron/37.6.0 "
    "Safari/537.36"
)
LINUX_CHROME = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


@pytest.mark.parametrize(
    ("request_headers", "expected"),
    [
        ({"user-agent": MAC_CHROME}, ("Chrome", "macOS", "desktop")),
        ({"user-agent": IPHONE}, ("Mobile Safari", "iOS", "mobile")),
        ({"user-agent": IPAD}, ("Mobile Safari", "iOS", "tablet")),
        (
            {
                "user-agent": ANDROID_REDUCED,
                "sec-ch-ua-mobile": "?1",
                "sec-ch-ua-platform": '"Android"',
            },
            ("Chrome", "Android", "mobile"),
        ),
        (
            {
                "user-agent": ANDROID_REDUCED,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Android"',
            },
            ("Chrome", "Android", "tablet"),
        ),
        ({"user-agent": CLAUDE_DESKTOP}, ("Electron", "macOS", "desktop")),
        (
            {
                "user-agent": LINUX_CHROME,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Linux"',
            },
            ("Chrome", "Linux", "desktop"),
        ),
    ],
)
def test_device_props_follow_user_agent_and_client_hints(request_headers, expected):
    props = device_props(request_headers)
    assert (props["browser"], props["os"], props["device_type"]) == expected
    assert props["browser_version"]


def test_device_props_record_nothing_without_a_user_agent():
    assert device_props({}) == {
        "browser": None,
        "browser_version": None,
        "os": None,
        "device_type": None,
    }


def test_collector_overrides_emitter_device_fields(client, database):  # noqa: F811
    payload = {**event(), "device_type": "mobile", "browser": "forged"}
    admitted = {**headers(client), "User-Agent": MAC_CHROME}
    response = client.post("/api/events", json={"events": [payload]}, headers=admitted)
    assert response.status_code == 200
    with database() as conn:
        raw = conn.execute(
            "SELECT envelope FROM events WHERE event_id=%s", (payload["event_id"],)
        ).fetchone()[0]
    stored = json.loads(raw) if isinstance(raw, str) else raw
    assert stored["device_type"] == "desktop"
    assert stored["browser"] == "Chrome"
    assert stored["browser_version"] == "141.0.0.0"
    assert stored["os"] == "macOS"
