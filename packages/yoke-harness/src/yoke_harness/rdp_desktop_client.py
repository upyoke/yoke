"""View the existing XFCE display over a bounded credential-owned RDP route."""

from __future__ import annotations

from contextlib import ExitStack
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
# Logical window bounds; Retina uses two framebuffer pixels per logical pixel.
INITIAL_WINDOW_BOUNDS = (1280, 800)
MAC_WINDOW_SCALE = 2


def _window_geometry(width, height):
    factor = min(1, INITIAL_WINDOW_BOUNDS[0] / width, INITIAL_WINDOW_BOUNDS[1] / height)
    density = MAC_WINDOW_SCALE if sys.platform == "darwin" else 1
    return round(width * factor * density), round(height * factor * density)


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
                reasons = re.findall(r"\b(?:ERRCONNECT|ERRINFO)_[A-Z_]+\b", line)
                if reasons:
                    evidence["reason"] = reasons[-1]
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


def _client_failure(code, evidence, log_path):
    reason = evidence.get("reason", "client_exit_unknown")
    if reason == "ERRINFO_LOGOFF_BY_USER":
        recovery = "The remote desktop logged off; inspect /var/log/xrdp-sesman.log for a window manager that exited immediately, repair the fixture session, then rerun desktop-access --view."
    elif reason in {"ERRCONNECT_CONNECT_FAILED", "ERRCONNECT_CONNECT_TRANSPORT_FAILED"}:
        recovery = "Check the registered desktop port and xrdp service, repair the RDP route, then rerun desktop-access --view."
    elif reason in {"ERRCONNECT_LOGON_FAILURE", "ERRCONNECT_AUTHENTICATION_FAILED"}:
        recovery = "Repair the registered desktop_user and desktop_password fixture secret, then rerun desktop-access --view."
    else:
        recovery = "Inspect the retained client log, repair the named client or remote desktop failure, then rerun desktop-access --view."
    return f"desktop_view_failed: {reason}; FreeRDP exited {code}; retained log: {log_path}; {recovery}"


class DesktopView:
    """One FreeRDP viewer. Close stops the client and its SSH forward."""

    def __init__(self, stack, process, reader, log, log_path, evidence, user, receipt):
        self._stack = stack
        self.process = process
        self._reader = reader
        self._log = log
        self.log_path = log_path
        self.evidence = evidence
        self.user = user
        self.receipt = receipt
        self._client_stopped = False
        self._forward_closed = False

    @classmethod
    def open(cls, project, machine, settings, password, receipt, run):
        executable = shutil.which("sdl-freerdp") or shutil.which("sdl-freerdp3")
        if not executable:
            raise DesktopAccessError("desktop_rdp_client_missing: " + CLIENT_RECOVERY)
        environment = receipt["environment"]
        probe = run(
            shlex.join(
                [
                    "env",
                    *[f"{k}={v}" for k, v in environment.items()],
                    "xwininfo",
                    "-root",
                ]
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
        stack = ExitStack()
        host, port, user = stack.enter_context(desktop_forward(project, settings))
        launched = False
        try:
            opened = cls._launch(
                stack,
                executable,
                host,
                port,
                user,
                machine,
                settings,
                password,
                receipt,
                width,
                height,
                depth,
            )
            launched = True
            return opened
        finally:
            if not launched:
                stack.close()

    @classmethod
    def _launch(
        cls,
        stack,
        executable,
        host,
        port,
        user,
        machine,
        settings,
        password,
        receipt,
        width,
        height,
        depth,
    ):
        authority = f"[{host}]" if ":" in host else host
        window_width, window_height = _window_geometry(width, height)
        argv = [
            executable,
            f"/v:{authority}:{port}",
            f"/u:{user}",
            "/d:",
            "/from-stdin:force",
            # Only the loopback SSH route trusts SSH's verified host key.
            "/cert:ignore"
            if settings["desktop_route"] == "ssh-forward"
            else "/cert:deny",
            "/log-level:INFO",
            "/timeout:15000",
            # SDL retains /size as local window dimensions and negotiates the
            # smart-sizing dimensions remotely. Keep the existing XFCE size.
            f"/size:{window_width}x{window_height}",
            f"/smart-sizing:{width}x{height}",
            f"/bpp:{depth}",
            f"/t:Yoke desktop: {machine}",
        ]
        local_environment = dict(os.environ)
        local_environment.pop("SDL_VIDEODRIVER", None)
        if sys.platform == "darwin":
            # Continuous RDP updates can keep the SDL loop inside Metal's
            # nextDrawable wait instead of pumping Cocoa input events.
            local_environment["SDL_RENDER_DRIVER"] = "opengl"
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
        process = None
        reader = None
        evidence = {}
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
        except FileNotFoundError:
            cls._abandon(process, reader, log, log_path, evidence)
            raise DesktopAccessError(
                f"desktop_rdp_client_missing: retained log: {log_path}; "
                + CLIENT_RECOVERY
            ) from None
        except (OSError, subprocess.TimeoutExpired) as exc:
            cls._abandon(process, reader, log, log_path, evidence)
            raise DesktopAccessError(
                f"desktop_view_unavailable: {type(exc).__name__}; retained log: {log_path}; check workstation client permissions and resources, then rerun desktop-access --view"
            ) from None
        return cls(stack, process, reader, log, log_path, evidence, user, receipt)

    @staticmethod
    def _abandon(process, reader, log, log_path, evidence):
        try:
            if process is not None:
                _stop(process, log_path)
        finally:
            if reader is not None:
                reader.join(timeout=CLEANUP_TIMEOUT)
                if reader.is_alive():
                    evidence["capture_failed"] = True
            log.close()

    def stop_client(self):
        if self._client_stopped:
            return
        self._client_stopped = True
        try:
            if self.process is not None:
                _stop(self.process, self.log_path)
        finally:
            if self._reader is not None:
                self._reader.join(timeout=CLEANUP_TIMEOUT)
                if self._reader.is_alive():
                    self.evidence["capture_failed"] = True
            self._log.close()

    def close_forward(self):
        if self._forward_closed:
            return
        self._forward_closed = True
        self._stack.close()

    def close(self):
        try:
            self.stop_client()
        finally:
            self.close_forward()

    def outcome(self, code):
        if self.evidence.get("capture_failed"):
            raise DesktopAccessError(
                f"desktop_view_log_failed: retained partial log: {self.log_path}; repair temporary storage and retry"
            )
        local_quit = (
            code in LOCAL_QUIT_CODES
            and self.evidence.get("connected")
            and self.evidence.get("cancelled")
            and not self.evidence.get("client_failed")
        )
        if code and not local_quit:
            raise DesktopAccessError(
                _client_failure(code, self.evidence, self.log_path)
            )
        return {
            "user": self.user,
            "desktop_session": self.receipt["desktop_session"],
            "display": self.receipt["environment"]["DISPLAY"],
            "viewer": "closed",
            "log_path": self.log_path,
            "client_exit_code": self.process.returncode,
        }


def view_desktop(project, machine, settings, password, receipt, run):
    opened = DesktopView.open(project, machine, settings, password, receipt, run)
    code = None
    try:
        try:
            code = opened.process.wait()
        except KeyboardInterrupt:
            # The caller may close a deliberately retained viewer with Ctrl-C.
            pass
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DesktopAccessError(
                f"desktop_view_unavailable: {type(exc).__name__}; retained log: {opened.log_path}; check workstation client permissions and resources, then rerun desktop-access --view"
            ) from None
        finally:
            opened.stop_client()
        return opened.outcome(code)
    finally:
        opened.close_forward()
