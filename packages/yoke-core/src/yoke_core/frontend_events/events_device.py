# Generated from the installed structured-events Pack; run build_frontend_events.
"""Server-side bot, browser, OS and device classification for collected events.

The collector is the only authority for these fields: it parses the request
User-Agent with the maintained uap-core parser (``ua-parser``) and lets the
User-Agent Client Hints the browser sent by default override it. Viewport
size is a layout signal and never decides device type.
"""

import math
import re

try:
    from ua_parser import parse
except ImportError as error:  # pragma: no cover - exercised by installs only
    raise ImportError(
        "events_device_parser_missing: add ua-parser>=1.0 to the collector's "
        "Python dependencies (pip install 'ua-parser[regex]'), then restart"
    ) from error

from .events_attribution import is_bot

MOBILE_OS = {"Android", "iOS", "Windows Phone", "KaiOS"}
# uap-core names macOS by its historical family; Client Hints say "macOS".
OS_NAMES = {"Mac OS X": "macOS"}


def _hint(headers, name):
    value = headers.get(name)
    return value.strip().strip('"') if value else None


def device_props(headers):
    """Return is_bot, browser, browser_version, os and device_type for a request.

    ``headers`` is any case-insensitive mapping of request headers. Reads
    ``User-Agent``, ``Sec-CH-UA-Mobile`` and ``Sec-CH-UA-Platform``.
    """
    user_agent = headers.get("user-agent") or ""
    result = parse(user_agent)
    agent, system, device = result.user_agent, result.os, result.device
    mobile = _hint(headers, "sec-ch-ua-mobile")
    platform = _hint(headers, "sec-ch-ua-platform")
    os_name = platform or (system and OS_NAMES.get(system.family, system.family))
    if not result.string and mobile is None:
        device_type = None
    elif mobile == "?1":
        device_type = "mobile"
    elif device and (
        device.family == "iPad" or (device.brand or "").endswith("_Tablet")
    ):
        device_type = "tablet"
    elif mobile is None and os_name in MOBILE_OS:
        device_type = "mobile"
    else:
        device_type = "desktop"
    version = agent and ".".join(
        part
        for part in (agent.major, agent.minor, agent.patch, agent.patch_minor)
        if part
    )
    props = {
        "is_bot": is_bot(user_agent),
        "browser": agent.family if agent else None,
        "browser_version": version or None,
        "os": os_name or None,
        "device_type": device_type,
    }
    ios_version = re.search(r"(?:CPU (?:iPhone )?OS|iPhone OS) (\d+(?:_\d+)*)", user_agent)
    if ios_version:
        props["os_version"] = ios_version[1].replace("_", ".")
    return props


STRING_FACTS = {"os_version", "device_model", "cpu_architecture", "cpu_bitness", "gpu_renderer", "connection_type"}
NUMBER_FACTS = {
    "cpu_cores": (1, 1024, True), "device_memory_gb": (0, 1024, False),
    "pixel_ratio": (0, 16, False), "touch_points": (0, 256, True),
    "color_depth": (1, 64, True), "connection_downlink_mbps": (0, 100000, False),
}


def merge_device_props(event, device):
    """Drop invalid optional facts, then stamp the collector's authoritative facts."""
    for name in STRING_FACTS:
        if name in event and not (isinstance(event[name], str) and 0 < len(event[name]) <= 128):
            event.pop(name)
    for name, (low, high, integer) in NUMBER_FACTS.items():
        if name not in event:
            continue
        value = event[name]
        valid = type(value) in (int, float) and low <= value <= high and math.isfinite(value)
        if valid and integer:
            valid = value == int(value)
        if name in {"device_memory_gb", "pixel_ratio"} and valid:
            valid = value > 0
        if not valid:
            event.pop(name)
    event.update(device)
