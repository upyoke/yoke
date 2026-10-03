"""View the existing XFCE display over a bounded credential-owned RDP route."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading

from yoke_harness.desktop_access import DesktopAccessError
from yoke_harness.desktop_forward import desktop_forward

CLEANUP_TIMEOUT = 5
CLIENT_RECOVERY = "Install FreeRDP's sdl-freerdp on the executing workstation (macOS: brew install freerdp; Linux: install freerdp-sdl), then rerun desktop-access --view."
# FreeRDP SDL reports CONN_FAILED on local quit when its event-handle check
# observes cancellation. Never accept that code without the client evidence.
LOCAL_QUIT_CODES = {131, 145}


def _capture_output(source, destination, password, evidence):
    try:
        with source:
            for line in source:
                destination.write(line.replace(password, "[redacted]"))
                destination.flush()
                if "[gdi_init_ex]: Local framebuffer format" in line:
                    evidence["connected"] = True
                if (
                    "[freerdp_abort_connect_context]: ERRCONNECT_CONNECT_CANCELLED"
                    in line
                ):
                    evidence["cancelled"] = True
                if "[exception]" in line:
                    evidence["client_failed"] = True
    except (OSError, ValueError):
        evidence["capture_failed"] = True


def _stop(process, log_path):
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
                    f"desktop_view_cleanup_failed: retained log: {log_path}; terminate the owned FreeRDP client before retrying"
                ) from None
            raise DesktopAccessError(
                f"desktop_view_unresponsive: FreeRDP required a forced stop; retained log: {log_path}; inspect the log and rerun desktop-access --view"
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
            "/log-level:INFO",
            "/timeout:15000",
            f"/size:{width}x{height}",
            f"/bpp:{depth}",
            f"/t:Yoke desktop: {machine}",
        ]
        local_environment = dict(os.environ)
        local_environment.pop("SDL_VIDEODRIVER", None)
        if sys.platform == "darwin":
            # Continuous RDP updates can keep the SDL loop inside Metal's
            # nextDrawable wait instead of pumping Cocoa input events.
            local_environment["SDL_RENDER_DRIVER"] = "opengl"
        process = None
        reader = None
        evidence = {}
        code = None
        try:
            descriptor, log_path = tempfile.mkstemp(
                prefix="yoke-desktop-view-", suffix=".log"
            )
        except OSError:
            raise DesktopAccessError(
                "desktop_view_log_unavailable: repair the workstation temporary directory permissions and free space, then rerun desktop-access --view"
            ) from None
        log = os.fdopen(descriptor, "w", encoding="utf-8")
        print(f"desktop_view_log: {log_path}", file=sys.stderr, flush=True)
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                env=local_environment,
            )
            reader = threading.Thread(
                target=_capture_output,
                args=(process.stdout, log, password, evidence),
                daemon=True,
            )
            reader.start()
            process.stdin.write(password + "\n")
            process.stdin.close()
            code = process.wait()
        except KeyboardInterrupt:
            # The caller may close a deliberately retained viewer with Ctrl-C.
            pass
        except (OSError, subprocess.TimeoutExpired):
            raise DesktopAccessError(
                f"desktop_view_unavailable: retained log: {log_path}; "
                + CLIENT_RECOVERY
            ) from None
        finally:
            try:
                if process is not None:
                    _stop(process, log_path)
            finally:
                if reader is not None:
                    reader.join(timeout=CLEANUP_TIMEOUT)
                    if reader.is_alive():
                        evidence["capture_failed"] = True
                log.close()
        if evidence.get("capture_failed"):
            raise DesktopAccessError(
                f"desktop_view_log_failed: retained partial log: {log_path}; repair temporary storage and retry"
            )
        local_quit = (
            code in LOCAL_QUIT_CODES
            and evidence.get("connected")
            and evidence.get("cancelled")
            and not evidence.get("client_failed")
        )
        if code and not local_quit:
            raise DesktopAccessError(
                f"desktop_view_failed: FreeRDP exited {code}; retained log: {log_path}; inspect the log and verify the registered XFCE desktop and RDP route; "
                + CLIENT_RECOVERY
            )
    return {
        "user": user,
        "desktop_session": receipt["desktop_session"],
        "display": environment["DISPLAY"],
        "viewer": "closed",
        "log_path": log_path,
        "client_exit_code": process.returncode,
    }
