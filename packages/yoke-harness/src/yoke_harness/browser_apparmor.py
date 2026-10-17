"""Provision exact-path user-namespace allowances for Yoke's Chromium builds."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from yoke_contracts import terminal_detached_process
from yoke_harness.system_privileges import command_authority

RESTRICTION = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
PROFILE_DIRECTORY = Path("/etc/apparmor.d")
# Projected by browser setup. "0" launches Chromium with its sandbox off.
SANDBOX_ENV = "YOKE_BROWSER_CHROMIUM_SANDBOX"
RECOVERY = (
    "Allow Yoke system setup through root or sudo, ensure AppArmor tooling is installed, "
    "then retry yoke qa browser setup. Chromium requires its sandbox; "
    "the host user-namespace restriction stays enabled."
)
EXECUTABLES_JS = r"""
const path = require('path');
const fs = require('fs');
const root = path.dirname(require.resolve('playwright-core/package.json'));
const { registry } = require(path.join(root, 'lib/coreBundle.js')).registry;
console.log(JSON.stringify(['chromium', 'chromium-headless-shell'].map(name =>
  fs.realpathSync(registry.findExecutable(name).executablePath()))));
"""

# Run via the same OS authority as Linux system packages. Arguments are data,
# never shell text. Replace the stable profile on updates, removing old paths.
INSTALL_PROFILE = r"""
import os, pathlib, subprocess, sys, tempfile
destination, content, parser = sys.argv[1:]
directory = pathlib.Path(destination).parent
fd, temporary = tempfile.mkstemp(prefix='.yoke-chromium-', dir=directory)
try:
    with os.fdopen(fd, 'w') as stream:
        stream.write(content)
        stream.flush()
        os.fchmod(stream.fileno(), 0o644)
    os.replace(temporary, destination)
    result = subprocess.run([parser, '-r', destination], capture_output=True, text=True)
    if result.returncode:
        print(result.stderr or result.stdout or 'AppArmor profile load failed', file=sys.stderr)
        sys.exit(result.returncode)
except OSError as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(1)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
"""

SANDBOX_PROBE_JS = r"""
const { chromium } = require('playwright');
(async () => {
  for (const executablePath of JSON.parse(process.argv[1])) {
    const browser = await chromium.launch({ executablePath, headless: true, chromiumSandbox: true });
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exit(1); });
"""


def _failure(detail):
    # Provisioning failures are one plain diagnostic, not a Chromium log dump.
    reason = " ".join(str(detail).splitlines()[0].split())
    return RuntimeError(f"browser_apparmor_setup_failed: {reason}. {RECOVERY}")


def _profile(browser, executables):
    identity = hashlib.sha256(str(browser.resolve()).encode()).hexdigest()[:16]
    name = f"yoke-chromium-{identity}"
    rules = ["abi <abi/4.0>,", "include <tunables/global>", ""]
    for index, executable in enumerate(executables):
        path = Path(executable)
        if not path.is_absolute() or any(c in executable for c in '*?[]{}^"\\\n\r'):
            raise _failure(
                "Chromium path cannot be expressed as an exact AppArmor attachment"
            )
        profile_name = f"{name}-{index}"
        rules.extend(
            [
                f'profile {profile_name} "{executable}" flags=(unconfined) {{',
                "  userns,",
                "}",
                "",
            ]
        )
    return PROFILE_DIRECTORY / name, "\n".join(rules)


def _current(destination, content):
    try:
        return destination.read_text() == content
    except OSError:
        return False


def _sandbox_probe(browser, toolchain, env, executables):
    # The kernel's profile list requires CAP_MAC_ADMIN. Prove actual sandboxed
    # launches without demanding root on every later browser startup.
    return terminal_detached_process.run(
        [str(toolchain.node), "-e", SANDBOX_PROBE_JS, json.dumps(executables)],
        cwd=str(browser),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )


def _sandbox_off(emit, reason):
    detail = " ".join(str(reason).split())
    emit(
        "[browser-auto-bootstrap] Chromium sandbox unavailable without root "
        f"({detail}); launching with the sandbox off. "
        "To enable the sandbox, allow system setup through root or passwordless sudo, "
        "then retry yoke qa browser setup."
    )
    return False


def ensure_chromium_apparmor(browser, toolchain, *, env, emit, autoinstall=True):
    """Return whether later Chromium launches keep the sandbox on.

    A restricted host with no root or passwordless sudo finishes setup and
    returns False so launches set ``chromiumSandbox`` false. A loaded profile,
    or one this call installs, returns True. An interactive sudo password is
    not requested.
    """
    if not sys.platform.startswith("linux"):
        return True
    try:
        if not RESTRICTION.exists() or RESTRICTION.read_text().strip() == "0":
            return True
        result = terminal_detached_process.run(
            [str(toolchain.node), "-e", EXECUTABLES_JS],
            cwd=str(browser),
            env=env,
            capture_output=True,
            text=True,
        )
        executables = json.loads(result.stdout) if result.returncode == 0 else None
        if (
            not isinstance(executables, list)
            or len(executables) != 2
            or not all(isinstance(path, str) and path for path in executables)
        ):
            raise _failure(
                f"cannot resolve Chromium binaries: {result.stderr or result.stdout}"
            )
        destination, content = _profile(browser, executables)
        if (
            _current(destination, content)
            and _sandbox_probe(browser, toolchain, env, executables).returncode == 0
        ):
            emit("[browser-auto-bootstrap] Chromium AppArmor sandbox already verified")
            return True
        if not autoinstall:
            raise _failure(
                "AppArmor restricts Chromium user namespaces and YOKE_BROWSER_AUTOINSTALL=0"
            )
        parser = shutil.which("apparmor_parser")
        if not parser and Path("/usr/sbin/apparmor_parser").is_file():
            parser = "/usr/sbin/apparmor_parser"
        if not parser:
            raise _failure(
                "AppArmor restricts Chromium user namespaces but apparmor_parser is missing"
            )
        try:
            prefix, interactive = command_authority(
                "browser_chromium_sandbox_unavailable: AppArmor restricts unprivileged user namespaces"
            )
        except RuntimeError as exc:
            return _sandbox_off(emit, exc)
        # An interactive password prompt hangs setup and fights the wizard.
        if interactive:
            return _sandbox_off(
                emit, "enabling the sandbox would ask for an interactive sudo password"
            )
        emit(
            "[browser-auto-bootstrap] provisioning Chromium AppArmor userns profiles..."
        )
        # Only a sudo password prompt keeps the terminal.
        run = subprocess.run if interactive else terminal_detached_process.run
        result = run(
            [
                *prefix,
                sys.executable,
                "-c",
                INSTALL_PROFILE,
                str(destination),
                content,
                parser,
            ],
            env=env,
            text=True,
            capture_output=not interactive,
        )
        if result.returncode:
            raise _failure(
                f"cannot install/load Chromium profile: {result.stderr or result.stdout or result.returncode}"
            )
        # A parser success alone is insufficient: both binaries must sandbox.
        probe = _sandbox_probe(browser, toolchain, env, executables)
        if probe.returncode:
            raise _failure(
                f"Chromium sandbox launch failed: {probe.stderr or probe.stdout}"
            )
        emit("[browser-auto-bootstrap] Chromium AppArmor userns profiles verified")
        return True
    except (OSError, ValueError) as exc:
        raise _failure(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise _failure(
            "Chromium sandbox check timed out; check browser process health"
        ) from exc
