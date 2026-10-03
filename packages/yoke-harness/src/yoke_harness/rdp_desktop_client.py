"""View the existing XFCE display over a bounded credential-owned RDP route."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess

from yoke_harness.desktop_access import DesktopAccessError
from yoke_harness.desktop_forward import desktop_forward

CLEANUP_TIMEOUT = 5
CLIENT_RECOVERY = "Install FreeRDP's sdl-freerdp on the executing workstation (macOS: brew install freerdp; Linux: install freerdp-sdl), then rerun desktop-access --view."


def _stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=CLEANUP_TIMEOUT)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=CLEANUP_TIMEOUT)
            except subprocess.TimeoutExpired:
                raise DesktopAccessError(
                    "desktop_view_cleanup_failed: terminate the owned FreeRDP client before retrying"
                ) from None


def view_desktop(project, machine, settings, password, receipt, run):
    executable = shutil.which("sdl-freerdp") or shutil.which("sdl-freerdp3")
    if not executable:
        raise DesktopAccessError("desktop_rdp_client_missing: " + CLIENT_RECOVERY)
    environment = receipt["environment"]
    probe = run(
        shlex.join(
            ["env", *[f"{k}={v}" for k, v in environment.items()], "xwininfo", "-root"]
        ),
        timeout=20,
    )
    values = [
        re.search(rf"^\s*{key}:\s*(\d+)\s*$", probe.stdout, re.MULTILINE)
        for key in ("Width", "Height", "Depth")
    ]
    if probe.returncode or not all(values):
        raise DesktopAccessError(
            "desktop_view_geometry_unavailable: repair xwininfo on the registered XFCE display and retry"
        )
    width, height, depth = (int(value[1]) for value in values)
    if (
        not 64 <= width <= 16384
        or not 64 <= height <= 16384
        or depth not in {16, 24, 32}
    ):
        raise DesktopAccessError(
            "desktop_view_geometry_invalid: inspect the registered XFCE display before retrying"
        )
    with desktop_forward(project, settings) as (host, port, user):
        authority = f"[{host}]" if ":" in host else host
        argv = [
            executable,
            f"/v:{authority}:{port}",
            f"/u:{user}",
            "/d:",
            "/from-stdin:force",
            "/cert:tofu",
            "/log-level:OFF",
            "/timeout:15000",
            f"/size:{width}x{height}",
            f"/bpp:{depth}",
            f"/t:Yoke desktop: {machine}",
        ]
        local_environment = dict(os.environ)
        local_environment.pop("SDL_VIDEODRIVER", None)
        process = None
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                env=local_environment,
            )
            process.stdin.write(password + "\n")
            process.stdin.close()
            code = process.wait()
            if code:
                raise DesktopAccessError(
                    f"desktop_view_failed: FreeRDP exited {code}; verify the registered WSL/Linux user, fixture secret and RDP route; "
                    + CLIENT_RECOVERY
                )
        except KeyboardInterrupt:
            # The caller may close a deliberately retained viewer with Ctrl-C.
            pass
        except (OSError, subprocess.TimeoutExpired):
            raise DesktopAccessError(
                "desktop_view_unavailable: " + CLIENT_RECOVERY
            ) from None
        finally:
            if process is not None:
                _stop(process)
    return {
        "user": user,
        "desktop_session": receipt["desktop_session"],
        "display": environment["DISPLAY"],
        "viewer": "closed",
    }
