"""Read-only checks and operator windows on the Test Machine's native browser."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import subprocess
import time
from urllib.parse import urlsplit

import httpx

from yoke_harness.ssh_linux_preserved_entries import SNAP_CHROMIUM_HOME_ENTRY
from yoke_harness.ssh_mac_preserved_state import SAFARI_COOKIE_HOME_ENTRY


def browser_kind() -> str:
    system = platform.system()
    if system not in {"Linux", "Darwin"}:
        raise RuntimeError(
            "desktop_browser_unsupported: use a Linux Chromium or macOS Safari Test Machine."
        )
    return "Chromium" if system == "Linux" else "Safari"


def quit_browser(kind: str) -> None:
    if kind == "Chromium":
        from yoke_harness.linux_desktop_chromium import quit_chromium

        try:
            quit_chromium()
        except RuntimeError as exc:
            raise RuntimeError(
                "desktop_browser_quit_not_proved: close Chromium on the Test Machine, then retry."
            ) from exc
    else:
        from yoke_harness.ssh_mac_sign_in_apps import quit_sign_in_apps

        def run(command, **kwargs):
            return subprocess.run(
                command, shell=True, text=True, capture_output=True, **kwargs
            )

        result = quit_sign_in_apps(run, str(os.getuid()))
        if not result.ok:
            raise RuntimeError(f"{result.error_code}: {result.evidence['recovery']}")


def cookie_file(kind: str) -> Path:
    if kind == "Safari":
        return Path.home() / SAFARI_COOKIE_HOME_ENTRY / "Cookies.binarycookies"
    root = Path.home() / SNAP_CHROMIUM_HOME_ENTRY
    state = root / "Local State"
    try:
        selected = (
            json.loads(state.read_text()).get("profile", {}).get("last_used", "Default")
            if state.exists()
            else "Default"
        )
        if (
            not isinstance(selected, str)
            or not selected
            or Path(selected).name != selected
            or selected in {".", ".."}
        ):
            raise ValueError
    except (OSError, ValueError, AttributeError):
        raise RuntimeError(
            "desktop_browser_profile_unreadable: repair Chromium's Local State profile selection, then retry; no sign-in window was opened."
        ) from None
    profile = root / selected
    modern = profile / "Network/Cookies"
    return modern if modern.exists() else profile / "Cookies"


def native_cookies(kind: str):
    """Keep decrypted values in memory; never put them in argv or evidence."""
    from http.cookiejar import CookieJar
    import browser_cookie3

    store = cookie_file(kind)
    if not store.exists():
        return CookieJar()
    try:
        loader = (
            browser_cookie3.chromium if kind == "Chromium" else browser_cookie3.safari
        )
        return loader(cookie_file=str(store))
    except Exception:
        raise RuntimeError(
            "desktop_browser_cookie_store_unreadable: allow this terminal to read the native browser's "
            "cookie store and unlock its user keyring, then retry; no sign-in window was opened."
        ) from None


_SELECTOR_CHECK = r"""
const fs = require('fs');
const { chromium } = require('playwright');
const { checkSites } = require('./src/verify-sign-in');
const { launchOptions } = require('./src/browser-executable');
(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({...launchOptions(), headless:true, chromiumSandbox:true});
  try {
    const context = await browser.newContext();
    await context.addCookies(input.cookies);
    console.log(JSON.stringify({sites:await checkSites(context, input.checks)}));
  } finally { await browser.close(); }
})().catch(() => { console.error('desktop_browser_headless_check_failed'); process.exitCode=1; });
"""


def check_desktop(identity, runtime, *, kind: str) -> list[dict]:
    """Apply declared probes to native cookies, never an automation profile."""
    if not identity.sites:
        raise RuntimeError(
            "desktop_browser_sites_undeclared: declare this identity's sites and accounts in browser-control settings before authorizing the desktop browser."
        )
    quit_browser(kind)
    cookies = native_cookies(kind)
    outcomes = []
    selectors = [
        check for check in identity.sites if check.signed_in_selector is not None
    ]
    if selectors:
        hosts = {urlsplit(check.probe_url).hostname for check in selectors}
        values = [
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "secure": c.secure,
                "httpOnly": c.has_nonstandard_attr("HTTPOnly"),
                **({"expires": c.expires} if c.expires else {}),
            }
            for c in cookies
            if any(
                host == c.domain.lstrip(".")
                or host.endswith("." + c.domain.lstrip("."))
                for host in hosts
            )
        ]
        result = subprocess.run(
            [str(runtime.node), "-e", _SELECTOR_CHECK],
            cwd=runtime.runtime_dir,
            env=runtime.env,
            input=json.dumps(
                {"cookies": values, "checks": [c.as_probe() for c in selectors]}
            ),
            text=True,
            capture_output=True,
            timeout=300,
        )
        try:
            if result.returncode:
                raise ValueError
            outcomes.extend(json.loads(result.stdout)["sites"])
        except (ValueError, KeyError, TypeError):
            raise RuntimeError(
                "desktop_browser_headless_check_failed: repair the browser runtime with yoke qa browser setup, then retry; no sign-in window was opened."
            ) from None
    with httpx.Client(cookies=cookies, follow_redirects=False, timeout=15) as client:
        for check in identity.sites:
            if check.signed_in_status is None:
                continue
            try:
                status = client.get(check.probe_url).status_code
                outcomes.append(
                    {
                        "site": check.site,
                        "state": "signed_in"
                        if status == check.signed_in_status
                        else "expired",
                        "detail": f"answered {status}",
                    }
                )
            except httpx.HTTPError:
                outcomes.append(
                    {
                        "site": check.site,
                        "state": "unreachable",
                        "detail": "probe request failed",
                    }
                )
    by_site = {entry["site"]: entry for entry in outcomes}
    return [
        {**by_site[c.site], "origin": c.origin, "account": c.account}
        for c in identity.sites
    ]


def window_count(kind: str) -> int:
    command = (
        ["/usr/bin/osascript", "-e", 'tell application "Safari" to count windows']
        if kind == "Safari"
        else ["xdotool", "search", "--onlyvisible", "--class", "chromium"]
    )
    result = subprocess.run(command, text=True, capture_output=True, timeout=15)
    if kind == "Safari" and result.returncode == 0:
        return int(result.stdout.strip())
    if kind == "Chromium" and result.returncode in {0, 1}:
        return len(result.stdout.splitlines())
    raise RuntimeError(
        "desktop_browser_window_probe_failed: allow desktop automation and repair xdotool or Safari Automation access, then retry."
    )


def sign_in_window(kind: str, urls: list[str]) -> None:
    """Open only the expired sites in the native browser and await the operator."""
    from yoke_contracts.designed_wait import announce_designed_wait

    command = (
        ["/usr/bin/open", "-a", "Safari", *urls]
        if kind == "Safari"
        else ["/snap/bin/chromium", "--new-window", *urls]
    )
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    announce_designed_wait(
        "the operator to sign in and close the native browser windows",
        cadence="checks native desktop windows every 1s",
        max_wait_seconds=1800,
    )
    started = time.monotonic()
    seen = False
    while time.monotonic() - started < 1800:
        windows = window_count(kind)
        seen |= windows > 0
        if seen and not windows:
            quit_browser(kind)
            return
        if not seen and time.monotonic() - started > 30:
            raise RuntimeError(
                "desktop_browser_window_unavailable: open the Test Machine desktop and repair its native browser, then retry."
            )
        time.sleep(1)
    raise RuntimeError(
        "desktop_browser_sign_in_timeout: close the native browser windows after signing in, then rerun without resetting its profile."
    )
