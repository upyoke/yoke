"""Find and drive the approval page in a running identity browser.

``yoke browser open`` starts each identity browser with a loopback DevTools
port that Chromium records in the profile's DevToolsActivePort file; every
identity profile lives under ~/.yoke-browser-identities/<project>/<identity>.
The test machine's installed Yoke runs this through ``yoke browser devtools``,
so the workstation driver needs nothing on the host but that Yoke.
"""

from __future__ import annotations


import json
import os
from pathlib import Path
import time
from urllib.parse import quote
from urllib.request import urlopen

from yoke_harness.linux_devtools_page import DevToolsPage
from yoke_contracts.machine_browser_approval import CONNECTED_CONFIRMATION

STORE = ".yoke-browser-identities"
TAB_WAIT_SECONDS = 15
CONTROL_ATTEMPTS = 40
NAVIGATION_ATTEMPTS = 40
POLL_SECONDS = 0.25


def _get_json(port, path):
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return json.loads(response.read())


def live_ports(home=None):
    """DevTools ports of every running identity browser on this machine."""
    root = Path(home or os.path.expanduser("~")) / STORE
    ports = []
    for marker in sorted(root.glob("*/*/DevToolsActivePort")):
        try:
            port = int(marker.read_text(encoding="utf-8").split()[0])
            _get_json(port, "/json/version")
        except (OSError, ValueError, IndexError):
            continue
        ports.append(port)
    return ports


def close(port):
    """Ask the identity browser on *port* to exit; quiet when it already has."""
    try:
        page = DevToolsPage(_get_json(port, "/json/version")["webSocketDebuggerUrl"])
    except (OSError, KeyError, ValueError):
        return
    try:
        page.call("Browser.close")
    except OSError:
        pass  # Chromium may drop the socket before it replies.
    finally:
        page.socket.close()


def _pages(port):
    return [p for p in _get_json(port, "/json/list") if p.get("type") == "page"]


def _all_pages():
    return [(port, page) for port in live_ports() for page in _pages(port)]


def tabs(origin):
    deadline = time.monotonic() + TAB_WAIT_SECONDS
    while True:
        pages = _all_pages()
        urls = [page.get("url", "") for _, page in pages]
        if (
            any(url.startswith(origin + "/") for url in urls)
            or time.monotonic() >= deadline
        ):
            return {"urls": urls, "identity_browsers": len(live_ports())}
        time.sleep(POLL_SECONDS)


def approve(allowed_urls, label):
    found = next(
        ((port, page) for port, page in _all_pages() if page.get("url") in allowed_urls),
        None,
    )
    if found is None:
        return {"state": "browser_tab_missing"}
    port, match = found
    start = match["url"]
    with urlopen(
        f"http://127.0.0.1:{port}/json/activate/{quote(match['id'], safe='')}",
        timeout=5,
    ):
        pass
    press = (
        "(() => { if (location.href !== "
        + json.dumps(start)
        + ") return 'browser_tab_changed';"
        " const control = [...document.querySelectorAll('button, [role=button]')].find(e =>"
        " (e.getAttribute('aria-label') || e.innerText || '').trim() === "
        + json.dumps(label)
        + " && !e.disabled); if (!control) return 'approval_control_missing';"
        " control.click(); return 'pressed'; })()"
    )
    page = DevToolsPage(match["webSocketDebuggerUrl"])
    state = "approval_control_missing"
    for _ in range(CONTROL_ATTEMPTS):
        reply = page.call("Runtime.evaluate", expression=press, returnByValue=True)
        state = reply.get("result", {}).get("value") or "approval_control_missing"
        if state in ("pressed", "browser_tab_changed"):
            break
        time.sleep(POLL_SECONDS)
    if state != "pressed":
        return {"state": state}
    for _ in range(NAVIGATION_ATTEMPTS):
        time.sleep(POLL_SECONDS)
        url = next(
            (p.get("url") for p in _pages(port) if p.get("id") == match["id"]), None
        )
        if url is not None and url != start:
            return {"state": "approved", "starting_url": start, "result_url": url}
        try:
            confirmed = page.call(
                "Runtime.evaluate",
                returnByValue=True,
                expression="location.href === "
                + json.dumps(start)
                + " && [...document.querySelectorAll('h1')].some(e => "
                + "e.getClientRects().length && e.innerText.trim() === "
                + json.dumps(CONNECTED_CONFIRMATION)
                + ")",
            )
        except (OSError, ValueError, IndexError):
            confirmed = {}
        if url == start and confirmed.get("result", {}).get("value") is True:
            return {
                "state": "approved_in_place",
                "starting_url": start,
                "result_url": url,
            }
    return {"state": "approval_navigation_missing"}


def run_command(command: str, arguments: list[str]) -> dict:
    """Run one registered command; ``ok`` False names why it failed."""
    try:
        if command == "tabs" and len(arguments) == 1:
            return {"ok": True, **tabs(arguments[0])}
        if command == "approve" and len(arguments) == 2:
            return {"ok": True, **approve(json.loads(arguments[0]), arguments[1])}
    except (OSError, ValueError) as exc:
        return {
            "ok": False,
            "reason": "identity_browser_devtools_failed",
            "recovery": f"DevTools failed: {exc}. Confirm the identity browser "
            "opened by `yoke browser open` is running and responsive, then rerun.",
        }
    return {
        "ok": False,
        "reason": "identity_browser_command_unknown",
        "recovery": "Use `yoke browser devtools tabs ORIGIN` or "
        "`yoke browser devtools approve URLS_JSON LABEL`.",
    }


__all__ = ["approve", "live_ports", "run_command", "tabs"]
