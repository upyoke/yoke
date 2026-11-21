"""View a test machine desktop in FreeRDP over a bounded credential-owned RDP route."""

from __future__ import annotations

from contextlib import ExitStack
import os
import re
import shutil
import subprocess
import sys
import threading

from yoke_contracts.owner_private_path import create_owner_private_temporary
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


def _certificate_option(host, port, settings):
    """SSH's verified host key vouches for the loopback forward; direct pins TOFU."""
    if settings["desktop_route"] == "ssh-forward":
        return "/cert:ignore"
    from yoke_cli.config import machine_config
    from yoke_harness.rdp_certificate_pin import pinned_certificate

    fingerprint = pinned_certificate(
        host, port, DesktopAccessError, yoke_home=machine_config.yoke_home()
    )
    return f"/cert:fingerprint:sha256:{fingerprint}"


def _client_executable():
    executable = shutil.which("sdl-freerdp") or shutil.which("sdl-freerdp3")
    if not executable:
        raise DesktopAccessError("desktop_rdp_client_missing: " + CLIENT_RECOVERY)
    return executable


def _user_options(user):
    """A DOMAIN\\user name splits so an empty /d: never overrides its domain."""
    domain, _, name = user.rpartition("\\")
    return [f"/u:{name}", f"/d:{domain}"]


class DesktopView:
    """One FreeRDP viewer. Close stops the client and its SSH forward."""

    def __init__(self, stack, process, reader, log, log_path, evidence, user, session):
        self._stack = stack
        self.process = process
        self._reader = reader
        self._log = log
        self.log_path = log_path
        self.evidence = evidence
        self.user = user
        self.session = session
        self._client_stopped = False
        self._forward_closed = False

    @classmethod
    def open(cls, project, test_machine, settings, password, receipt):
        """Fit the measured XFCE desktop to the local screen."""
        environment = receipt["environment"]
        resolution = receipt["resolution"]
        return cls.start(
            project, test_machine, settings, password,
            ["/f", f"/smart-sizing:{resolution}", f"/bpp:{receipt['depth']}"],
            {"desktop_session": receipt["desktop_session"],
             "display": environment["DISPLAY"], "resolution": resolution},
        )

    @classmethod
    def start(cls, project, test_machine, settings, password, display_options, session):
        """Launch FreeRDP with caller-owned display options and outcome fields."""
        executable = _client_executable()
        stack = ExitStack()
        host, port, user = stack.enter_context(desktop_forward(project, settings))
        launched = False
        try:
            certificate = _certificate_option(host, port, settings)
            if certificate.startswith("/cert:fingerprint:sha256:"):
                session = {**session, "certificate_sha256": certificate.rsplit(":", 1)[1]}
            opened = cls._launch(
                stack,
                [
                    executable,
                    f"/v:{f'[{host}]' if ':' in host else host}:{port}",
                    *_user_options(user),
                    "/from-stdin:force",
                    certificate,
                    "/log-level:INFO",
                    "/timeout:15000",
                    *display_options,
                    f"/t:Yoke desktop: {test_machine}",
                ],
                password,
                user,
                session,
            )
            launched = True
            return opened
        finally:
            if not launched:
                stack.close()

    @classmethod
    def _launch(cls, stack, argv, password, user, session):
        local_environment = dict(os.environ)
        local_environment.pop("SDL_VIDEODRIVER", None)
        if sys.platform == "darwin":
            # Continuous RDP updates can keep the SDL loop inside Metal's
            # nextDrawable wait instead of pumping Cocoa input events.
            local_environment["SDL_RENDER_DRIVER"] = "opengl"
        try:
            descriptor, private_log = create_owner_private_temporary(
                prefix="yoke-desktop-view-", suffix=".log"
            )
            log_path = str(private_log)
        except OSError:
            raise DesktopAccessError(
                "desktop_view_log_unavailable: repair the workstation temporary directory permissions and free space, then rerun desktop-access --view"
            ) from None
        log = os.fdopen(descriptor, "w", encoding="utf-8")
        print(f"desktop_view_log: {log_path}", file=sys.stderr, flush=True)
        print(f"Desktop resolution: {session['resolution']}", file=sys.stderr, flush=True)
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
        return cls(stack, process, reader, log, log_path, evidence, user, session)

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

    closing = "the viewer closes when verification finishes."

    def describe(self, test_machine):
        return f'A window titled "Yoke desktop: {test_machine}" will appear.'

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
            **self.session,
            "viewer": "closed",
            "log_path": self.log_path,
            "client_exit_code": self.process.returncode,
        }


def view_desktop(project, test_machine, settings, password, receipt):
    return watch_view(
        DesktopView.open(project, test_machine, settings, password, receipt)
    )


def watch_view(opened):
    """Wait for the viewer to close, then stop its client and forward."""
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
