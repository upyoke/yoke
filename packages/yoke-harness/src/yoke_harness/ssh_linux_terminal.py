"""Bounded tmux sessions with transcripts for headless Linux QA."""

from __future__ import annotations

import shlex
import time
from uuid import uuid4
from typing import Any, Mapping, Sequence

from yoke_harness.test_machine_types import HostActionResult

SCREENSHOT_DEFERRAL = "headless_linux_screenshot_unavailable"
SCREENSHOT_RECOVERY = "Use a macOS Test Machine for GUI screenshot evidence; Linux QA uses tmux transcripts."


class LinuxTerminal:
    """One disposable tmux session inside a persistent, leased test host."""

    def __init__(self, control: Any) -> None:
        self.control = control
        self.session = "yoke-qa-" + uuid4().hex

    def command(self, *args: str):
        return self.control._run(shlex.join(["tmux", *args]), timeout=20)

    def open(self, entry_surface: str, size: tuple[int, int] = (120, 40)) -> bool:
        result = self.command(
            "new-session",
            "-d",
            "-s",
            self.session,
            "-x",
            str(size[0]),
            "-y",
            str(size[1]),
        )
        if result.returncode:
            return False
        self.command("set-option", "-t", self.session, "history-limit", "100000")
        self.send(entry_surface + "; printf '\\n__YOKE_EXIT_%s\\n' \"$?\"")
        return True

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

    def close(self) -> None:
        self.command("kill-session", "-t", self.session)


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
            rows.append({"key": step["key"], "ok": transcript is not None})
            if transcript is None:
                return HostActionResult(
                    False,
                    {
                        "steps": rows,
                        "recovery": "Inspect the declared expectation and the host's tmux session; rerun after repair.",
                    },
                    "linux_tmux_expectation_timeout",
                )
        completed = any(row["key"] == required_completion and row["ok"] for row in rows)
        return HostActionResult(
            completed,
            {
                "terminal_backend": "tmux",
                "steps": rows,
                "transcript": terminal.transcript(),
                "capture_degraded_reason": SCREENSHOT_DEFERRAL,
                "designed_deferrals": [
                    {
                        "code": SCREENSHOT_DEFERRAL,
                        "outcome": "deferred",
                        "recovery": SCREENSHOT_RECOVERY,
                    }
                ],
            },
            None if completed else "terminal_completion_not_proved",
        )
    finally:
        terminal.close()


def diagnose_linux_terminal(control: Any) -> HostActionResult:
    token = "YOKE_BRIDGE_" + uuid4().hex
    terminal = LinuxTerminal(control)
    try:
        opened = terminal.open(
            "printf '%s%s\\n' " + shlex.join([token[:12], token[12:]])
        )
        transcript = terminal.wait_for(token, time.monotonic() + 10) if opened else None
        checks = [
            {"name": "tmux_session", "ok": opened},
            {
                "name": "tmux_input_transcript",
                "ok": transcript is not None,
                "transcript": token if transcript is not None else "",
            },
            {
                "name": "gui_screenshot",
                "ok": True,
                "outcome": "deferred",
                "code": SCREENSHOT_DEFERRAL,
                "recovery": SCREENSHOT_RECOVERY,
            },
        ]
        ok = opened and transcript is not None
        return HostActionResult(
            ok,
            {"checks": checks, "terminal_backend": "tmux"},
            None if ok else "linux_tmux_bridge_unavailable",
        )
    finally:
        terminal.close()
