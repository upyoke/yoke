"""Collector-side browser, OS and device classification contract."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from events_device import device_props, merge_device_props  # noqa: E402

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


FACTS = {
    "os_version": "15.4", "device_model": "Pixel 9", "cpu_architecture": "arm",
    "cpu_bitness": "64", "gpu_renderer": "Apple M4", "connection_type": "4g",
    "cpu_cores": 8, "device_memory_gb": 8, "pixel_ratio": 2,
    "touch_points": 0, "color_depth": 24, "connection_downlink_mbps": 0,
}


@pytest.mark.parametrize("field,value", FACTS.items())
def test_optional_device_facts_preserved(field, value):
    event = {field: value, "custom": "kept"}
    merge_device_props(event, device_props({}))
    assert event[field] == value
    assert event["custom"] == "kept"


@pytest.mark.parametrize("field", FACTS)
@pytest.mark.parametrize("value", [None, True, {}, [], "x" * 129, -1, float("inf"), float("nan"), 100001])
def test_invalid_optional_device_facts_dropped(field, value):
    event = {field: value, "event_name": "PageViewed"}
    merge_device_props(event, {})
    assert event == {"event_name": "PageViewed"}


@pytest.mark.parametrize("field,value", [
    ("cpu_cores", 0), ("cpu_cores", 1.5), ("cpu_cores", 1025),
    ("device_memory_gb", 0), ("pixel_ratio", 0), ("pixel_ratio", 17),
    ("touch_points", 0.5), ("touch_points", 257), ("color_depth", 0), ("color_depth", 65),
])
def test_numeric_device_bounds(field, value):
    event = {field: value}
    merge_device_props(event, {})
    assert event == {}


@pytest.mark.parametrize("agent,version", [
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X)", "18.5"),
    ("Mozilla/5.0 (iPad; CPU OS 17_4_1 like Mac OS X)", "17.4.1"),
])
def test_ios_os_version_overrides_emitter(agent, version):
    event = {"os_version": "forged"}
    merge_device_props(event, device_props({"user-agent": agent}))
    assert event["os_version"] == version


@pytest.mark.parametrize("agent", [MAC_CHROME, "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", ""])
def test_other_os_versions_not_inferred(agent):
    props = device_props({"user-agent": agent})
    assert "os_version" not in props
    event = {"os_version": "15.4"}
    merge_device_props(event, props)
    assert event["os_version"] == "15.4"
