"""Hold FreeRDP for a Windows GUI operation; secrets travel only on stdin."""

from contextlib import contextmanager
import os
import shutil
import subprocess
import time

from yoke_cli.config.capability_secrets import read_machine_capability_secret
from yoke_contracts.machine_config.desktop_access import (
    DESKTOP_PASSWORD_KEY,
    validate_desktop_settings,
)
from yoke_contracts.machine_config.test_machine import test_machine_capability_type
from yoke_harness.desktop_access import DesktopAccessError
from yoke_harness.desktop_forward import desktop_forward
from yoke_harness.windows_desktop_state import active_windows_sessions

START_TIMEOUT = 45
AUTH_TIMEOUT = 30
CLIENT_RECOVERY = "install FreeRDP's sdl-freerdp on the executing workstation (macOS: brew install freerdp; Linux: install the freerdp-sdl package), or log in with a human RDP client and keep the dedicated desktop open"


def _client():
    executable = shutil.which("sdl-freerdp") or shutil.which("sdl-freerdp3")
    if not executable:
        raise DesktopAccessError("windows_rdp_client_missing: " + CLIENT_RECOVERY)
    return executable


def _password(project, machine):
    cap_type = test_machine_capability_type(machine)
    password = read_machine_capability_secret(project, cap_type, DESKTOP_PASSWORD_KEY)
    if password is None:
        raise DesktopAccessError(
            f"desktop_password_missing: import the registered login with yoke projects capability secret set --project {project} --cap-type {cap_type} --key desktop_password --value-stdin"
        )
    if "\n" in password or "\r" in password:
        raise DesktopAccessError(
            "desktop_password_invalid: re-import the desktop password as one line"
        )
    return password


def _argv(executable, host, port, user):
    authority = f"[{host}]" if ":" in host else host
    return [
        executable,
        f"/v:{authority}:{port}",
        f"/u:{user}",
        "/d:",
        "/from-stdin:force",
        "/cert:tofu",
        "/log-level:OFF",
        "/timeout:15000",
    ]


def _authenticate(argv, password):
    try:
        result = subprocess.run(
            [*argv, "+auth-only"],
            input=password + "\n",
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=AUTH_TIMEOUT,
            check=False,
        )
        if result.returncode:
            raise DesktopAccessError(
                "windows_desktop_authentication_failed: re-import the registered desktop login, verify RDP access, and retry; "
                + CLIENT_RECOVERY
            )
    except (OSError, subprocess.TimeoutExpired):
        raise DesktopAccessError(
            "windows_desktop_authentication_unavailable: verify RDP access and retry; "
            + CLIENT_RECOVERY
        ) from None


def prove_windows_credentials(*, project, machine, settings):
    executable = _client()
    password = _password(project, machine)
    with desktop_forward(project, settings) as (host, port, user):
        _authenticate(_argv(executable, host, port, user), password)
    return {
        "user": user,
        "credential_proof": "authenticated",
        "desktop_session": "not_started",
    }


def _stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                raise DesktopAccessError(
                    "windows_desktop_cleanup_failed: terminate the held FreeRDP client on this workstation before retrying"
                ) from None


@contextmanager
def windows_desktop_session(control):
    """Reuse an active login or connect until the GUI operation has finished."""
    settings = control._desktop_settings
    project = control._desktop_project
    route = validate_desktop_settings(settings)
    if not route or route["desktop_protocol"] != "rdp":
        raise DesktopAccessError(
            "windows_rdp_route_required: register the Windows RDP desktop route with yoke test-machine settings-replace"
        )
    user = route["desktop_user"]
    if (
        user.rsplit("\\", 1)[-1].casefold()
        != settings["user"].rsplit("\\", 1)[-1].casefold()
    ):
        raise DesktopAccessError(
            "windows_desktop_user_mismatch: register the same Windows account for SSH and RDP so its interactive capture task can run"
        )
    sessions = active_windows_sessions(control)
    matching = [
        s
        for s in sessions
        if s["user"].casefold() == user.rsplit("\\", 1)[-1].casefold()
    ]
    if sessions and not matching:
        raise DesktopAccessError(
            "windows_desktop_user_conflict: ask the active desktop user to finish and log out, then retry; no RDP login was started"
        )
    if matching:
        yield {
            "desktop_session": "reused",
            "windows_session_id": matching[0]["session_id"],
        }
        return
    executable = _client()
    password = _password(project, settings["resource_name"])
    with desktop_forward(project, settings) as (host, port, user):
        argv = _argv(executable, host, port, user)
        process = None
        try:
            process = subprocess.Popen(
                [*argv, "/size:1280x800"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                env={**os.environ, "SDL_VIDEODRIVER": "dummy"},
            )
            process.stdin.write(password + "\n")
            process.stdin.close()
            deadline = time.monotonic() + START_TIMEOUT
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise DesktopAccessError(
                        "windows_desktop_start_failed: verify the registered desktop login and FreeRDP client, then retry; "
                        + CLIENT_RECOVERY
                    )
                sessions = active_windows_sessions(control)
                matching = [
                    s
                    for s in sessions
                    if s["user"].casefold() == user.rsplit("\\", 1)[-1].casefold()
                ]
                if matching:
                    yield {
                        "desktop_session": "started",
                        "windows_session_id": matching[0]["session_id"],
                    }
                    if process.poll() is not None:
                        raise DesktopAccessError(
                            "windows_desktop_connection_lost: repair the RDP connection and retry the GUI operation"
                        )
                    return
                if sessions:
                    raise DesktopAccessError(
                        "windows_desktop_user_conflict: another desktop login appeared; ask its user to finish and retry"
                    )
                time.sleep(0.5)
            raise DesktopAccessError(
                "windows_desktop_start_timeout: verify FreeRDP can open the registered login and retry; "
                + CLIENT_RECOVERY
            )
        except (OSError, subprocess.TimeoutExpired):
            raise DesktopAccessError(
                "windows_desktop_client_unavailable: " + CLIENT_RECOVERY
            ) from None
        finally:
            if process is not None:
                _stop(process)
