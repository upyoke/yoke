"""Collector-side browser, OS and device classification contract."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from events_device import device_props  # noqa: E402

MAC_CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
ANDROID = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"user-agent": MAC_CHROME}, ("Chrome", "macOS", "desktop")),
        (
            {
                "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 "
                "Mobile/15E148 Safari/604.1"
            },
            ("Mobile Safari", "iOS", "mobile"),
        ),
        (
            {
                "user-agent": "Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 "
                "Mobile/15E148 Safari/604.1"
            },
            ("Mobile Safari", "iOS", "tablet"),
        ),
        (
            {
                "user-agent": ANDROID,
                "sec-ch-ua-mobile": "?1",
                "sec-ch-ua-platform": '"Android"',
            },
            ("Chrome", "Android", "mobile"),
        ),
        (
            {
                "user-agent": ANDROID,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Android"',
            },
            ("Chrome", "Android", "tablet"),
        ),
        (
            {
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Claude/1.0.211 "
                "Chrome/138.0.7204.251 Electron/37.6.0 Safari/537.36"
            },
            ("Electron", "macOS", "desktop"),
        ),
    ],
)
def test_device_props_follow_user_agent_and_client_hints(headers, expected):
    props = device_props(headers)
    assert (props["browser"], props["os"], props["device_type"]) == expected
    assert props["browser_version"]


def test_device_props_record_nothing_without_a_user_agent():
    assert device_props({}) == {
        "is_bot": False,
        "browser": None,
        "browser_version": None,
        "os": None,
        "device_type": None,
    }


def test_device_props_flag_bot_user_agents():
    assert device_props({"user-agent": "HeadlessChrome"})["is_bot"] is True
