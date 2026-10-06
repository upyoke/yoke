"""Discover installed Chromium and prove a sandboxed test-page launch."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

from yoke_cli.config import browser_executable

LAUNCH_PROBE_JS = r"""
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: process.argv[1],
    headless: true, chromiumSandbox: true, timeout: 15000 });
  try {
    const page = await browser.newPage();
    await page.goto('data:text/html,<title>Yoke browser probe</title>', { timeout: 15000 });
    if (await page.title() !== 'Yoke browser probe') throw new Error('test page did not load');
    console.log('ok');
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exit(1); });
"""
DOWNLOAD_RECOVERY = (
    "Allow cdn.playwright.dev, playwright.download.prss.microsoft.com, and "
    "playwright.azureedge.net, or install Chromium/Google Chrome locally, "
    "then retry yoke qa browser setup."
)


def candidates(saved: str | None = None) -> list[str]:
    paths = [saved] if saved else []
    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "chrome",
    ):
        executable = shutil.which(name)
        if executable:
            paths.append(executable)
    if sys.platform.startswith("linux"):
        paths.extend(
            ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium")
        )
    if sys.platform == "darwin":
        for root in (Path("/Applications"), Path.home() / "Applications"):
            paths.extend(
                str(root / app / "Contents/MacOS" / binary)
                for app, binary in (
                    ("Google Chrome.app", "Google Chrome"),
                    ("Chromium.app", "Chromium"),
                )
            )
    if sys.platform == "win32":
        for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            if os.environ.get(key):
                root = Path(os.environ[key])
                paths.extend(
                    str(root / relative)
                    for relative in (
                        "Google/Chrome/Application/chrome.exe",
                        "Chromium/Application/chrome.exe",
                    )
                )
    return list(
        dict.fromkeys(str(Path(p).absolute()) for p in paths if Path(p).is_file())
    )


def probe_installed(browser, toolchain, env, executable):
    """Prove the selected executable can open a sandboxed test page."""
    return subprocess.run(
        [str(toolchain.node), "-e", LAUNCH_PROBE_JS, executable],
        cwd=str(browser),
        env=env,
        capture_output=True,
        text=True,
        timeout=40,
    )


def use_installed(browser, toolchain, env, *, emit, saved=None) -> bool:
    failures = []
    for executable in candidates(saved):
        try:
            result = probe_installed(browser, toolchain, env, executable)
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(f"{executable}: {type(exc).__name__}")
            continue
        if result.returncode == 0 and result.stdout.strip() == "ok":
            if executable != saved:
                browser_executable.save(executable)
            browser_executable.project_environment(env, executable)
            emit(
                f"[browser-auto-bootstrap] system Chromium verified with a test page: {executable}"
            )
            return True
        failures.append(
            f"{executable}: {(result.stderr or result.stdout).strip()[-1000:]}"
        )
    if failures:
        emit(
            "[browser-auto-bootstrap] installed browser launch checks failed: "
            + " | ".join(failures)
        )
    return False


def download_failure(result, tail: str) -> RuntimeError:
    output = ((result.stdout or "") + (result.stderr or "")).lower()
    blocked = any(
        marker in output
        for marker in (
            "<html",
            "<!doctype html",
            "site unavailable",
            "openresty",
            "end of central directory record signature not found",
        )
    )
    reason = (
        f"browser_download_blocked: exit {result.returncode}; "
        "the browser download was blocked or corrupt (HTML block page or invalid ZIP)"
        if blocked
        else f"browser_install_failed: exit {result.returncode}"
    )
    return RuntimeError(f"{reason}\n{tail}\n{DOWNLOAD_RECOVERY}")
