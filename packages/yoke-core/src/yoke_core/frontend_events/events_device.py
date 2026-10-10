# Generated from the installed structured-events Pack; run build_frontend_events.
"""Server-side bot, browser, OS and device classification for collected events.

The collector is the only authority for these fields: it parses the request
User-Agent with the maintained uap-core parser (``ua-parser``) and lets the
User-Agent Client Hints the browser sent by default override it. Viewport
size is a layout signal and never decides device type.
"""

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
    return {
        "is_bot": is_bot(user_agent),
        "browser": agent.family if agent else None,
        "browser_version": version or None,
        "os": os_name or None,
        "device_type": device_type,
    }
