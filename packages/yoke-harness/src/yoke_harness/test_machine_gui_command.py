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
    """Adapt ssh-agent execution to the existing OS GUI command helpers."""

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
        if self.settings["os"] == "windows":
            from yoke_harness.windows_wsl_command import windows_wsl_command

            command = windows_wsl_command(command)
        argv = remote_exec_argv(
            host=self.settings["host"],
            user=self.settings["user"],
            known_hosts=self.known_hosts,
            command=[command],
            cloud_instance_id=self.settings.get("cloud_instance_id"),
        )
        try:
            if self.stream_output and timeout >= 1920 and input_text is None:
                output = _Progress(sys.stderr if self.json_mode else sys.stdout)
                errors = _Progress(sys.stderr, control_lines=True)
                process = subprocess.Popen(
                    argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                result = _stream_command(
                    argv,
                    process=process,
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
