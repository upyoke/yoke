"""Check Playwright's Linux libraries and install them with available OS authority."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from yoke_harness import browser_linux_deps
from yoke_harness.browser_apparmor import ensure_chromium_apparmor
from yoke_harness.system_privileges import command_authority

# The packaged Playwright version owns both validation and the apt package list.
# Validate the actual executable directories, without its successful-check cache.
DEPENDENCY_PROBE_JS = r"""
const path = require('path');
const fs = require('fs');
const root = path.dirname(require.resolve('playwright-core/package.json'));
const { registry } = require(path.join(root, 'lib/coreBundle.js')).registry;
(async () => {
  const directories = ['chromium', 'chromium-headless-shell'].map(name => {
    const executable = registry.findExecutable(name).executablePath();
    if (!fs.existsSync(executable)) throw new Error(`Browser executable missing: ${executable}`);
    return path.dirname(executable);
  });
  try {
    await registry._validateHostRequirements('javascript', '', directories, [], []);
    console.log(JSON.stringify({ missing: '' }));
  } catch (error) {
    if (!error.message.includes('Host system is missing dependencies')) throw error;
    console.log(JSON.stringify({ missing: error.message }));
  }
})().catch(error => { console.error(error.message); process.exit(1); });
"""


def _probe(browser, toolchain, env):
    result = subprocess.run(
        [str(toolchain.node), "-e", DEPENDENCY_PROBE_JS],
        cwd=str(browser),
        env=env,
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(result.stdout) if result.returncode == 0 else None
        if not isinstance(data, dict) or not isinstance(data.get("missing"), str):
            raise ValueError("invalid dependency probe result")
        return data
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"browser_dependency_check_failed: {result.stderr or result.stdout or exc}. "
            "Repair the packaged Playwright runtime and ldd, then retry yoke qa browser setup."
        ) from exc


def ensure_system_dependencies(
    browser: Path, toolchain, *, env, emit, autoinstall=True
):
    if not sys.platform.startswith("linux"):
        return
    ensure_chromium_apparmor(
        browser, toolchain, env=env, emit=emit, autoinstall=autoinstall
    )
    if not shutil.which("ldd"):
        raise RuntimeError(
            "browser_dependency_check_unavailable: ldd is missing. "
            "Install the Linux libc tooling, then retry yoke qa browser setup."
        )
    data = _probe(browser, toolchain, env)
    missing = data["missing"]
    if not missing:
        emit("[browser-auto-bootstrap] Linux system libraries already present")
        return
    if not autoinstall:
        raise RuntimeError(
            f"browser_system_libraries_missing: {missing}; YOKE_BROWSER_AUTOINSTALL=0"
        )
    prefix, interactive = command_authority(
        f"browser_system_packages_unavailable: {missing}\n"
        "This machine offers no way to install system packages. "
        "Run yoke qa browser setup in an interactive terminal with sudo access, "
        "or configure passwordless sudo for system package installation."
    )
    if browser_linux_deps.is_amazon_linux():
        commands = [browser_linux_deps.amazon_linux_chromium_deps_command()]
    else:
        if not shutil.which("apt-get"):
            raise RuntimeError(
                f"browser_package_manager_unavailable: {missing}. "
                "Install the named libraries with this Linux distribution package manager, "
                "then retry yoke qa browser setup."
            )
        # Running Playwright's installer as root makes it invoke apt directly.
        # One sudo invocation preserves the OS password prompt exactly once.
        commands = [
            [
                str(toolchain.node),
                str(browser / "node_modules/playwright/cli.js"),
                "install-deps",
                "chromium",
            ]
        ]
    authority = (
        "root"
        if not prefix
        else "interactive sudo"
        if interactive
        else "passwordless sudo"
    )
    emit(
        f"[browser-auto-bootstrap] installing missing Linux system libraries via {authority}..."
    )
    for command in commands:
        if not command:
            continue
        result = subprocess.run(
            [*prefix, *command],
            env=env,
            text=True,
            capture_output=not interactive,
        )
        if result.returncode:
            raise RuntimeError(
                f"browser_system_package_install_failed: {result.stderr or result.stdout or result.returncode}. "
                f"Missing dependencies: {missing}. "
                "Repair package-manager access, then retry yoke qa browser setup."
            )
    remaining = _probe(browser, toolchain, env)["missing"]
    if remaining:
        raise RuntimeError(
            f"browser_system_libraries_missing_after_install: {remaining}. "
            "Repair the named libraries, then retry yoke qa browser setup."
        )
    emit("[browser-auto-bootstrap] Linux system libraries verified")
