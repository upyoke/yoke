"""Provision exact-path user-namespace allowances for Yoke's Chromium builds."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from yoke_harness.system_privileges import command_authority

RESTRICTION = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")
PROFILES = Path("/sys/kernel/security/apparmor/profiles")
PROFILE_DIRECTORY = Path("/etc/apparmor.d")
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


def _failure(detail):
    return RuntimeError(f"browser_apparmor_setup_failed: {detail}. {RECOVERY}")


def _profile(browser, executables):
    identity = hashlib.sha256(str(browser.resolve()).encode()).hexdigest()[:16]
    name = f"yoke-chromium-{identity}"
    rules = ["abi <abi/4.0>,", "include <tunables/global>", ""]
    names = []
    for index, executable in enumerate(executables):
        path = Path(executable)
        if not path.is_absolute() or any(c in executable for c in '*?[]{}^"\\\n\r'):
            raise _failure(
                "Chromium path cannot be expressed as an exact AppArmor attachment"
            )
        profile_name = f"{name}-{index}"
        names.append(profile_name)
        rules.extend(
            [
                f'profile {profile_name} "{executable}" flags=(unconfined) {{',
                "  userns,",
                "}",
                "",
            ]
        )
    return PROFILE_DIRECTORY / name, "\n".join(rules), names


def _current(destination, content, names):
    try:
        loaded = PROFILES.read_text().splitlines()
        return destination.read_text() == content and all(
            f"{name} (unconfined)" in loaded for name in names
        )
    except OSError:
        return False


def ensure_chromium_apparmor(browser, toolchain, *, env, emit, autoinstall=True):
    if not sys.platform.startswith("linux"):
        return
    try:
        if not RESTRICTION.exists() or RESTRICTION.read_text().strip() == "0":
            return
        result = subprocess.run(
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
        destination, content, names = _profile(browser, executables)
        if _current(destination, content, names):
            emit(
                "[browser-auto-bootstrap] Chromium AppArmor userns profiles already loaded"
            )
            return
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
        prefix, interactive = command_authority(
            str(
                _failure(
                    "AppArmor restricts Chromium user namespaces and the Chromium profile needs system authority"
                )
            )
        )
        emit(
            "[browser-auto-bootstrap] provisioning Chromium AppArmor userns profiles..."
        )
        result = subprocess.run(
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
        # A parser success alone is insufficient: the kernel must have admitted it.
        if not _current(destination, content, names):
            raise _failure("Chromium AppArmor profiles were not loaded into the kernel")
        emit("[browser-auto-bootstrap] Chromium AppArmor userns profiles verified")
    except (OSError, ValueError) as exc:
        raise _failure(str(exc)) from exc
