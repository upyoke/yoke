"""Run a bounded command on a Test Machine's GUI through the existing SSH route."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
import subprocess
import sys

from yoke_contracts.machine_config.directories import create_private_directory
from yoke_contracts.machine_config.test_machine import validate_test_machine_settings
from yoke_harness.test_machine_remote_exec import (
    RemoteExecRefusal,
    SSH_AUTH_SOCK_ENV,
    known_hosts_path,
    remote_exec_argv,
    _stream_command,
)
from yoke_harness.native_windows.transport import encoded, process_script
from yoke_harness.native_windows.yoke_python import yoke_python_command


class _Progress:
    def __init__(self, destination, *, control_lines=False):
        self.destination, self.control_lines, self.pending = (
            destination,
            control_lines,
            "",
        )

    def write(self, value):
        if not self.control_lines:
            self.destination.write(value)
            return
        self.pending += value
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            if not line.startswith(("YOKE_COMMAND_HEARTBEAT", "YOKE_COMMAND_RECEIPT:")):
                self.destination.write(line + "\n")

    def flush(self):
        self.destination.flush()

    def finish(self):
        if self.pending and not self.pending.startswith("YOKE_COMMAND_"):
            self.destination.write(self.pending)
        self.destination.flush()


class _GuiSshControl:
    """Adapt ssh-agent execution to the existing OS GUI command helpers.

    Native Windows desktop commands use the full native transport instead
    (``_run_windows_desktop``); this control only probes over SSH there.
    """

    secret_values = ()

    def __init__(
        self,
        settings,
        yoke_home,
        desktop_password,
        stream_output=False,
        json_mode=False,
    ):
        self.settings = settings
        self.desktop_password = desktop_password
        self.secret_values = (desktop_password,) if desktop_password else ()
        self.known_hosts = known_hosts_path(yoke_home)
        self.desktop_port = int(settings.get("desktop_port", 3389))
        self.stream_output, self.json_mode, self.streamed = (
            stream_output,
            json_mode,
            False,
        )

    def _run(self, command, *, input_text=None, timeout=60):
        streamed = self.stream_output and timeout >= 1920 and input_text is None
        if self.settings["os"] == "wsl":
            from yoke_contracts.windows_wsl_command import (
                windows_wsl_command,
                windows_wsl_input,
            )

            # Windows caps a process command line at 32,767 characters; the
            # desktop helper alone exceeds it once encoded. Send it over stdin.
            command, input_text = windows_wsl_input(command, input_text)
            command = windows_wsl_command(command)
        elif self.settings["os"] == "windows":
            command = (
                "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "
                + encoded("$ErrorActionPreference='Stop'; " + command)
            )

        argv = remote_exec_argv(
            host=self.settings["host"],
            user=self.settings["user"],
            known_hosts=self.known_hosts,
            command=[command],
            cloud_instance_id=self.settings.get("cloud_instance_id"),
        )
        try:
            if streamed:
                output = _Progress(sys.stderr if self.json_mode else sys.stdout)
                errors = _Progress(sys.stderr, control_lines=True)
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE if input_text is not None else None,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                result = _stream_command(
                    argv,
                    process=process,
                    input_text=input_text,
                    redaction_secret=self.desktop_password,
                    stdout=output,
                    stderr=errors,
                    timeout=timeout,
                )
                errors.finish()
                self.streamed = True
            else:
                result = subprocess.run(
                    argv,
                    input=input_text,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise RemoteExecRefusal(
                "test_machine_gui_command_timeout",
                f"SSH GUI operation timed out after {timeout} seconds",
                "Check the Test Machine desktop and close any sign-in windows; "
                "verify its runtime and SSH route before retrying.",
            ) from exc
        except OSError as exc:
            raise RemoteExecRefusal(
                "test_machine_ssh_unavailable",
                f"could not start ssh: {exc}",
                "Install OpenSSH's ssh client and put it on PATH.",
            ) from exc
        for secret in self.secret_values:
            result.stdout = result.stdout.replace(secret, "[REDACTED]")
            result.stderr = result.stderr.replace(secret, "[REDACTED]")
        if result.returncode == 255:
            raise RemoteExecRefusal(
                "test_machine_ssh_failed",
                result.stderr.strip() or "SSH exited 255",
                "Check host reachability and the ssh-agent key. If the host was "
                "rebuilt, repair its pinned entry in "
                + str(self.known_hosts)
                + f" with `ssh-keygen -R {self.settings.get('cloud_instance_id') or self.settings['host']} -f {self.known_hosts}` before retrying.",
            )
        return result


def _run_windows_desktop(settings, argv, timeout):
    """Run *argv* in the signed-in Windows user's desktop session.

    The desktop handoff stages its script through the native Windows SSH
    transport, so this uses that transport itself, keyed by the Test
    Machine's imported SSH key, exactly as Machine QA does.
    """
    from yoke_contracts.machine_config.capability_secret_store import (
        test_machine_secret_path,
    )
    from yoke_harness.native_windows.desktop import desktop_script
    from yoke_harness.ssh_native_windows_host_operations import (
        SshNativeWindowsHostOperations,
    )

    name = settings["resource_name"]
    key_path = test_machine_secret_path(name, "ssh_private_key")
    if not key_path.is_file():
        raise RemoteExecRefusal(
            "desktop_ssh_key_missing",
            f"the SSH key for Test Machine {name} is not imported on this workstation",
            f"Import it with `yoke test-machine secret set --test-machine {name} "
            "--key ssh_private_key --value-file FILE`, then retry.",
        )
    control = SshNativeWindowsHostOperations(settings=settings, key_path=key_path)
    # ProcessStartInfo finds only .exe on PATH; Yoke is the yoke.cmd shim.
    script = (
        yoke_python_command(argv)
        if argv and argv[0] == "yoke"
        else process_script(argv)
    )
    result = desktop_script(control, script, timeout=timeout)
    result.output_streamed = False
    return result


def check_yoke_installation(*, project, test_machine, settings, yoke_home):
    """Check the login-shell PATH before opening any GUI desktop."""
    control = _GuiSshControl(settings, yoke_home, None)
    create_private_directory(control.known_hosts.parent)
    command = (
        "if (Get-Command yoke -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
        if settings["os"] == "windows"
        else shlex.join(["/bin/bash", "-lc", "command -v yoke"])
    )
    result = control._run(command, timeout=20)
    if result.returncode:
        raise RemoteExecRefusal(
            "test_machine_yoke_missing",
            f"Yoke is absent from test machine {test_machine}'s login-shell PATH",
            f"Run `yoke test-machine reset --test-machine "
            f"{test_machine} --baseline shell-preconfigured`, then retry authorization.",
        )


def run_gui_command(
    *,
    settings: dict,
    argv: list[str],
    yoke_home: Path,
    desktop_password=None,
    stream_output=False,
    json_mode=False,
):
    """Run on the declared OS desktop, preserving argv and its exit status."""
    settings = validate_test_machine_settings(settings)
    kind = settings["os"]
    if kind not in {"macos", "linux", "wsl", "windows"}:
        raise RemoteExecRefusal(
            "test_machine_os_unimplemented",
            f"{kind} Test Machines have no desktop command support on this Yoke version",
            "Run desktop commands on a macos, linux or wsl Test Machine, or upgrade Yoke.",
        )
    if not os.environ.get(SSH_AUTH_SOCK_ENV):
        raise RemoteExecRefusal(
            "test_machine_ssh_agent_unavailable",
            "SSH_AUTH_SOCK is not set",
            "Start an ssh-agent holding a key the host authorizes (ssh-add -l "
            "lists it), then retry from that shell.",
        )
    control = _GuiSshControl(
        settings, yoke_home, desktop_password, stream_output, json_mode
    )
    create_private_directory(control.known_hosts.parent)
    # The browser itself settles within 30 minutes; leave time for its cleanup
    # and verification before the outer GUI bridge reaches its bound.
    timeout = 1920
    if kind == "windows":
        return _run_windows_desktop(settings, argv, timeout)
    if kind == "macos":
        from yoke_harness.ssh_mac_gui_session import run_terminal_app_command

        result = run_terminal_app_command(control._run, argv=argv, timeout=timeout)
        result.output_streamed = control.streamed
        return result
    from yoke_harness.linux_desktop_session import desktop_command

    result = desktop_command(
        control, ["/bin/bash", "-lc", shlex.join(argv)], timeout=timeout
    )
    result.output_streamed = control.streamed
    return result
