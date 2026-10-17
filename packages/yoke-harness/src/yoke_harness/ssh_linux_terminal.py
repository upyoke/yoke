"""Bounded tmux sessions with transcripts for Linux QA, optionally on the desktop."""

from __future__ import annotations

import shlex
import time
from uuid import uuid4
from typing import Any, Mapping, Sequence

from yoke_harness.test_machine_types import HostActionResult


class LinuxTerminalWindowError(RuntimeError):
    def __init__(self, code, evidence):
        self.code, self.evidence = code, evidence
        super().__init__(f"{code}: {evidence}")


class LinuxTerminal:
    """One disposable tmux session inside a persistent, leased test host."""

    def __init__(self, control: Any) -> None:
        self.control = control
        self.session = "yoke-qa-" + uuid4().hex

    def command(self, *args: str):
        return self.control._run(shlex.join(["tmux", *args]), timeout=20)

    def open(
        self,
        entry_surface: str,
        size: tuple[int, int] = (120, 40),
        environment: Mapping[str, str] | None = None,
    ) -> bool:
        """Start the session; *environment* places it on the test user's desktop."""
        variables = [
            argument
            for name, value in sorted((environment or {}).items())
            if value
            for argument in ("-e", f"{name}={value}")
        ]
        result = self.command(
            "new-session",
            "-d",
            "-s",
            self.session,
            "-x",
            str(size[0]),
            "-y",
            str(size[1]),
            *variables,
        )
        if result.returncode:
            return False
        if self.command(
            "set-option", "-t", self.session, "history-limit", "100000"
        ).returncode:
            return False
        return self.send(entry_surface + "; printf '\\n__YOKE_EXIT_%s\\n' \"$?\"")

    def send(self, text: str) -> bool:
        if text in {"Enter", "C-c", "C-d", "Escape", "Tab", "Up", "Down"}:
            return self.command("send-keys", "-t", self.session, text).returncode == 0
        sent = self.command("send-keys", "-t", self.session, "-l", "--", text)
        return (
            sent.returncode == 0
            and self.command("send-keys", "-t", self.session, "Enter").returncode == 0
        )

    def transcript(self) -> str:
        result = self.command("capture-pane", "-p", "-t", self.session, "-S", "-")
        if result.returncode:
            raise RuntimeError("linux_tmux_transcript_failed")
        return result.stdout

    def show(self) -> bool:
        from yoke_harness.linux_desktop_session import desktop_command

        evidence = {"session": self.session, "commands": {}}

        def record(name, result):
            evidence["commands"][name] = {
                "returncode": result.returncode,
                "stderr": result.stderr,
            }
            return result.returncode == 0

        present = self.command("has-session", "-t", self.session)
        if not record("tmux_has_session", present):
            evidence["recovery"] = (
                "Inspect the case command and its exit; restart the recipe with a "
                "live tmux session before requesting a terminal window."
            )
            raise LinuxTerminalWindowError("linux_tmux_session_exited", evidence)
        launch = shlex.join(
            [
                "xfce4-terminal",
                "--disable-server",
                "--title",
                self.session,
                "--execute",
                "tmux",
                "attach-session",
                "-t",
                self.session,
            ]
        )
        # The window outlives this command; retain early launch errors without
        # leaving its inherited SSH pipes open.
        program = (
            "import shlex,subprocess,sys,tempfile,time; "
            "f=tempfile.TemporaryFile(); "
            "p=subprocess.Popen(shlex.split(sys.argv[1]), "
            "stdout=subprocess.DEVNULL,stderr=f,start_new_session=True); "
            "time.sleep(0.3); code=p.poll(); f.seek(0); "
            "sys.stderr.write(f.read().decode(errors='replace')); "
            "sys.exit(code if code is not None else 0)"
        )
        try:
            launched = desktop_command(
                self.control, ["python3", "-c", program, launch], timeout=10
            )
            launch_ok = record("launch", launched)
            visible = desktop_command(
                self.control,
                [
                    "xdotool",
                    "search",
                    "--sync",
                    "--onlyvisible",
                    "--name",
                    self.session,
                ],
                timeout=10,
            )
            visible_ok = record("xdotool", visible)
            if launch_ok and visible_ok:
                return True
        except RuntimeError as exc:
            evidence["desktop_error"] = str(exc)
        evidence["recovery"] = (
            "Provision and unlock the dedicated XFCE desktop; inspect launch and "
            "xdotool diagnostics, install xfce4-terminal and xdotool, then rerun."
        )
        raise LinuxTerminalWindowError("linux_terminal_window_unavailable", evidence)

    def wait_for(
        self, text: str, deadline: float, progress_callback=None
    ) -> str | None:
        while time.monotonic() < deadline:
            observed = self.transcript()
            if text in observed:
                return observed
            if progress_callback is not None:
                progress_callback()
            time.sleep(0.2)
        return None

    def close(self) -> bool:
        self.command("kill-session", "-t", self.session)
        return self.command("has-session", "-t", self.session).returncode == 1


def run_linux_terminal_case(
    control: Any,
    *,
    entry_surface: str,
    required_completion: str,
    steps: Sequence[Mapping[str, Any]],
    capture_checkpoints: Sequence[str],
    size: tuple[int, int] = (120, 40),
    progress_callback=None,
) -> HostActionResult:
    terminal = LinuxTerminal(control)
    rows = []
    try:
        if not terminal.open(entry_surface, size):
            return HostActionResult(
                False,
                {"recovery": "Install tmux and check the non-root SSH user's shell."},
                "linux_tmux_unavailable",
            )
        if capture_checkpoints and not terminal.show():
            return HostActionResult(
                False,
                {
                    "recovery": "Provision and unlock the dedicated XFCE desktop; install xfce4-terminal and xdotool, then rerun.",
                },
                "linux_terminal_window_unavailable",
            )
        for step in steps:
            if step.get("send") and not terminal.send(str(step["send"])):
                return HostActionResult(
                    False,
                    {
                        "steps": rows,
                        "recovery": "Repair the tmux input bridge and rerun.",
                    },
                    "linux_tmux_input_failed",
                )
            transcript = terminal.wait_for(
                str(step["expect"]),
                time.monotonic() + int(step.get("timeout_seconds", 30)),
                progress_callback,
            )
            rows.append(
                {
                    "key": step["key"],
                    "ok": transcript is not None,
                    "reached": transcript is not None,
                    "transcript": transcript or "",
                }
            )
            if transcript is None:
                return HostActionResult(
                    False,
                    {
                        "steps": rows,
                        "recovery": "Inspect the declared expectation and the host's tmux session; rerun after repair.",
                    },
                    "linux_tmux_expectation_timeout",
                )
            if str(step["key"]) in capture_checkpoints:
                try:
                    rows[-1].update(control.capture_terminal_checkpoint())
                except RuntimeError as exc:
                    return HostActionResult(
                        False,
                        {"steps": rows, "recovery": str(exc)},
                        "desktop_screenshot_failed",
                    )
        completed = any(row["key"] == required_completion and row["ok"] for row in rows)
        return HostActionResult(
            completed,
            {
                "terminal_backend": "tmux",
                "steps": rows,
                "transcript": terminal.transcript(),
            },
            None if completed else "terminal_completion_not_proved",
        )
    except LinuxTerminalWindowError as exc:
        return HostActionResult(False, exc.evidence, exc.code)
    finally:
        if not terminal.close():
            return HostActionResult(
                False,
                {
                    "recovery": "Restore SSH reachability and terminate the named yoke-qa tmux session before retrying.",
                    "session": terminal.session,
                },
                "linux_tmux_cleanup_failed",
            )


def diagnose_linux_terminal(control: Any) -> HostActionResult:
    token = "YOKE_BRIDGE_" + uuid4().hex
    terminal = LinuxTerminal(control)
    try:
        opened = terminal.open(
            "printf '%s%s\\n' " + shlex.join([token[:12], token[12:]])
        )
        transcript = terminal.wait_for(token, time.monotonic() + 10) if opened else None
        capture = control.capture_screenshot()
        from yoke_contracts.machine_qa_host_control import (
            PERSISTENT_TERMINAL_BRIDGE_CHECKS,
        )

        checks = [
            {"name": PERSISTENT_TERMINAL_BRIDGE_CHECKS[0], "ok": opened},
            {
                "name": PERSISTENT_TERMINAL_BRIDGE_CHECKS[1],
                "ok": transcript is not None,
                "transcript": token if transcript is not None else "",
            },
            {
                "name": PERSISTENT_TERMINAL_BRIDGE_CHECKS[2],
                "ok": capture.ok,
                **{
                    k: v for k, v in capture.evidence.items() if k != "capture_artifact"
                },
            },
        ]
        ok = opened and transcript is not None and capture.ok
        return HostActionResult(
            ok,
            {"checks": checks, "terminal_backend": "tmux"},
            None if ok else (capture.error_code or "linux_tmux_bridge_unavailable"),
        )
    finally:
        if not terminal.close():
            return HostActionResult(
                False,
                {
                    "recovery": "Restore SSH reachability and terminate the named yoke-qa tmux session before retrying.",
                    "session": terminal.session,
                },
                "linux_tmux_cleanup_failed",
            )
