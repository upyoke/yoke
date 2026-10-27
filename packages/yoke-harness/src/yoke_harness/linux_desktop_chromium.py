"""Drive the Linux desktop Chromium. Shipped after linux_devtools_page; no __future__ import."""

import json
import os
from pathlib import Path
import signal as signal
import subprocess
import sys
import time
from urllib.parse import quote
from urllib.request import urlopen

from yoke_harness.linux_devtools_page import DevToolsPage  # host: prepended source
from yoke_harness.machine_browser_approval import CONNECTED_CONFIRMATION
from yoke_harness import linux_chromium_processes as native_processes

CHROMIUM_NAMES = ("chromium", "chromium-browser")
# XFCE's exo-open falls back to debian-sensible-browser, which runs this.
BROWSER_ALTERNATIVE = Path("/usr/bin/x-www-browser")
DEVTOOLS_READY_SECONDS = 20
QUIT_WAIT_SECONDS = 30
TAB_WAIT_SECONDS = 15
CONTROL_ATTEMPTS = 40
NAVIGATION_ATTEMPTS = 40
POLL_SECONDS = 0.25
PROVISION = "Provision the desktop using .yoke/docs/verification/test-machines/linux-host-provisioning.md section 4; it installs Chromium with Ubuntu's chromium-browser wrapper and selects that as x-www-browser. Then rerun."


ChromiumRefusal = native_processes.ChromiumRefusal
browser_pids = native_processes.browser_pids


def user_data_dirs():
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return (config / "chromium", Path.home() / "snap/chromium/common/chromium")


def _get_json(port, path):
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return json.loads(response.read())


def devtools_port():
    for directory in user_data_dirs():
        try:
            port = int((directory / "DevToolsActivePort").read_text().split()[0])
            _get_json(port, "/json/version")
            return port
        except (OSError, ValueError, IndexError):
            continue
    return None


def quit_chromium():
    return native_processes.quit_processes(
        browser_pids, QUIT_WAIT_SECONDS, POLL_SECONDS
    )


_DESKTOP_XDG_MARK = "YOKE_DESKTOP_XDG:"
_SESSION = (
    "Install bash so a login shell can print XDG_DATA_DIRS (bash -lc), then rerun. "
    "Chromium starts with the desktop session's data dirs; the bare SSH environment lacks them."
)


def _login(script):
    try:
        return subprocess.run(
            ["bash", "-lc", script], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ChromiumRefusal(
            "linux_desktop_session_environment_unavailable", _SESSION
        ) from exc


def _marked(result, mark):
    parts = result.stdout.rsplit(mark, 1)
    if result.returncode != 0 or len(parts) != 2:
        raise ChromiumRefusal("linux_desktop_session_environment_unavailable", _SESSION)
    return parts[1]


def _desktop_env():
    value = _marked(
        _login(f'printf "{_DESKTOP_XDG_MARK}%s" "$XDG_DATA_DIRS"'), _DESKTOP_XDG_MARK
    )
    env = os.environ.copy()
    if value:
        env["XDG_DATA_DIRS"] = value
    else:
        env.pop("XDG_DATA_DIRS", None)
    return env


def _default_browser(link=BROWSER_ALTERNATIVE):
    """Resolve x-www-browser to the program desktop links actually run.

    A link straight to /snap/bin/chromium resolves to the snap launcher, which
    refuses to run as x-www-browser, so only a Chromium program counts.
    """
    return link.resolve()


def prepare():
    executable = _default_browser()
    if executable.name not in CHROMIUM_NAMES:
        found = executable if executable.exists() else "nothing"
        raise ChromiumRefusal(
            "linux_desktop_default_browser_not_chromium",
            f"The installer opens approval links through x-www-browser, which resolves to {found}. {PROVISION}",
        )
    if devtools_port() is not None:
        return {"chromium": "reused"}
    if not executable.exists():
        raise ChromiumRefusal("linux_desktop_chromium_missing", PROVISION)
    restarted = quit_chromium()
    for directory in user_data_dirs():
        (directory / "DevToolsActivePort").unlink(missing_ok=True)
    subprocess.Popen(
        [str(executable), "--remote-debugging-port=0"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=_desktop_env(),
    )
    deadline = time.monotonic() + DEVTOOLS_READY_SECONDS
    while devtools_port() is None:
        if time.monotonic() >= deadline:
            raise ChromiumRefusal(
                "linux_desktop_chromium_devtools_unavailable",
                f"{executable} started without a DevTools port in {' or '.join(str(d) for d in user_data_dirs())}. Use the distribution's Chromium build for the default profile, close Chromium on the desktop, then rerun.",
            )
        time.sleep(POLL_SECONDS)
    return {"chromium": "restarted" if restarted else "started"}


def _pages(port):
    return [p for p in _get_json(port, "/json/list") if p.get("type") == "page"]


def _port():
    port = devtools_port()
    if port is None:
        raise ChromiumRefusal(
            "linux_desktop_chromium_devtools_unavailable",
            "Desktop Chromium is not running with its DevTools port; rerun the case so the gate prepares it before the installer opens the approval link.",
        )
    return port


def tabs(origin):
    port = _port()
    deadline = time.monotonic() + TAB_WAIT_SECONDS
    while True:
        urls = [page.get("url", "") for page in _pages(port)]
        if (
            any(url.startswith(origin + "/") for url in urls)
            or time.monotonic() >= deadline
        ):
            return {"urls": urls}
        time.sleep(POLL_SECONDS)


def approve(allowed_urls, label):
    port = _port()
    match = next(
        (page for page in _pages(port) if page.get("url") in allowed_urls), None
    )
    if match is None:
        return {"state": "browser_tab_missing"}
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


def _refuse(reason, recovery):
    print(json.dumps({"ok": False, "reason": reason, "recovery": recovery}))
    raise SystemExit(69)


def main():
    command, arguments = sys.argv[1], sys.argv[2:]
    try:
        if command == "prepare":
            result = prepare()
        elif command == "tabs":
            result = tabs(arguments[0])
        elif command == "approve":
            result = approve(json.loads(arguments[0]), arguments[1])
        elif command == "quit":
            result = {"quit": quit_chromium()}
        else:
            raise ChromiumRefusal(
                "linux_desktop_chromium_command_unknown", "Use a registered command."
            )
    except ChromiumRefusal as refusal:
        _refuse(refusal.reason, refusal.recovery)
    except (OSError, ValueError) as exc:
        _refuse(
            "linux_desktop_chromium_devtools_failed",
            f"DevTools failed: {exc}. Confirm desktop Chromium is running and responsive, then rerun.",
        )
    print(json.dumps({"ok": True, **result}))
