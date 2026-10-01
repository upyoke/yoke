"""Desktop browser discovery and the shared Browser QA Chromium fallback."""

from __future__ import annotations

import configparser
import json
from pathlib import Path
import select
import shlex
import shutil
import subprocess
from typing import Mapping

from yoke_cli import browser_node_toolchain
from yoke_harness import browser_runtime_home, browser_setup

OPEN_TIMEOUT_SECONDS = 20
DESKTOP_LAUNCHERS = {
    "xdg-open",
    "exo-open",
    "gio",
    "sensible-browser",
    "gnome-open",
    "kfmclient",
}

# A successful launch and navigation acknowledges the open. The child owns
# the browser until its window closes; no QA daemon or QA profile is involved.
OPEN_CHROMIUM_JS = r"""
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: false, chromiumSandbox: true });
  browser.on('disconnected', () => process.exit(0));
  try {
    const page = await browser.newPage();
    await page.goto(process.argv[1], { waitUntil: 'commit', timeout: 15000 });
    console.log(JSON.stringify({ opened: true }));
  } catch (error) {
    console.log(JSON.stringify({ error: error.message }));
    await browser.close();
  }
})().catch(error => { console.log(JSON.stringify({ error: error.message })); process.exit(1); });
"""


def desktop_available(env: Mapping[str, str]) -> bool:
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def default_browser_command(env: Mapping[str, str]) -> list[str] | None:
    """Resolve the desktop association to an installed executable, not xdg-open.

    xdg-open can accept a request whose desktop launcher later fails. Checking
    the associated desktop entry prevents that handoff from claiming success.
    """
    settings = shutil.which("xdg-settings")
    if not settings:
        return _browser_alternative(env)
    result = subprocess.run(
        [settings, "get", "default-web-browser"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
        env=dict(env),
    )
    name = result.stdout.strip()
    if result.returncode or not name or Path(name).name != name:
        return _browser_alternative(env)
    data_home = Path(env.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    roots = [
        data_home,
        *(
            Path(p)
            for p in env.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
        ),
    ]
    for root in roots:
        entry = root / "applications" / name
        if not entry.is_file():
            continue
        config = configparser.ConfigParser(interpolation=None)
        config.read(entry)
        section = config["Desktop Entry"]
        if section.getboolean("Hidden", fallback=False):
            return None
        command = shlex.split(section.get("Exec", ""))
        executable = shutil.which(command[0], path=env.get("PATH")) if command else None
        if not executable or Path(executable).resolve().name in DESKTOP_LAUNCHERS:
            return _browser_alternative(env)
        # Desktop field codes are launch metadata, not literal browser args.
        return [part for part in command if not part.startswith("%")]
    return _browser_alternative(env)


def _browser_alternative(env: Mapping[str, str]) -> list[str] | None:
    # XFCE can associate URLs with exo-open even on a browserless desktop.
    # Debian's browser alternative is an actual installed browser symlink,
    # unlike exo-open/sensible-browser, which dispatch asynchronously.
    executable = shutil.which("x-www-browser", path=env.get("PATH"))
    if executable and Path(executable).resolve().name not in DESKTOP_LAUNCHERS:
        return [executable]
    return None


def open_system_browser(command: list[str], url: str, env: Mapping[str, str]) -> None:
    process = subprocess.Popen(
        [*command, url],
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        code = process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        return
    if code:
        raise RuntimeError(f"system_browser_open_failed: browser exited {code}")


def open_runtime_browser(url: str) -> None:
    """Use QA's materializer, installer, toolchain and browser cache unchanged."""
    runtime = browser_runtime_home.ensure_materialized()
    toolchain = browser_node_toolchain.ensure_node_toolchain()
    env = browser_setup.ensure_browser_runtime(runtime, toolchain, emit=lambda _: None)
    process = subprocess.Popen(
        [str(toolchain.node), "-e", OPEN_CHROMIUM_JS, url],
        cwd=runtime,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    try:
        assert process.stdout is not None
        ready, _, _ = select.select([process.stdout], [], [], OPEN_TIMEOUT_SECONDS)
        if not ready:
            raise RuntimeError(
                "browser_open_timeout: Chromium did not acknowledge the open"
            )
        result = json.loads(process.stdout.readline())
        if result.get("opened") is not True:
            raise RuntimeError(
                f"browser_open_failed: {result.get('error', 'no acknowledgement')}"
            )
    except Exception:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()
