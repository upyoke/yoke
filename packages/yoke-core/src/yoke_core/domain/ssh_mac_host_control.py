"""Machine-local SSH, PTY, Terminal, screenshot, and shell host_control adapter."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import shlex
import subprocess
from typing import Any, Mapping, Sequence
from uuid import uuid4

from yoke_core.domain import machine_config
from yoke_core.domain.host_control_executor import (
    HostActionResult,
    TestMachineMaterial,
    register_host_control_factory,
)
from yoke_core.domain.qa_artifact_handle import local_handle
from yoke_core.domain.ssh_mac_terminal_capture import (
    capture_screen,
    verify_terminal_bridge,
    wait_for_text,
)


SSH_OPTIONS = (
    "StrictHostKeyChecking=accept-new",
    "UserKnownHostsFile=/dev/null",
    "ConnectTimeout=10",
    "BatchMode=yes",
)


class SshMacHostControl:
    """Approved structured adapter for a project-owned macOS test resource."""

    def __init__(self, material: TestMachineMaterial) -> None:
        self.material = material
        self._key_path = Path(material.secret_paths["ssh_private_key"])
        self._host = material.settings["host"]
        self._user = material.settings["user"]
        facts = self._host_facts()
        self.home = str(facts["home"])
        self.shell = str(facts["shell"])
        self.xdg_bin_home = str(facts.get("xdg_bin_home") or "") or None

    def _ssh_argv(self, command: str) -> list[str]:
        return [
            "ssh",
            "-i",
            str(self._key_path),
            *[part for option in SSH_OPTIONS for part in ("-o", option)],
            f"{self._user}@{self._host}",
            command,
        ]

    def _run(
        self,
        command: str,
        *,
        input_text: str | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        argv = self._ssh_argv(command)
        try:
            return subprocess.run(
                argv,
                input=input_text,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return subprocess.CompletedProcess(
                argv,
                returncode=124,
                stdout="",
                stderr="host_control subprocess unavailable",
            )

    def _host_facts(self) -> dict[str, Any]:
        script = (
            "import json,os,pathlib;"
            "print(json.dumps({'home':str(pathlib.Path.home()),"
            "'shell':os.environ.get('SHELL') or '/bin/zsh',"
            "'xdg_bin_home':os.environ.get('XDG_BIN_HOME')}))"
        )
        result = self._run(
            "python3 -c " + shlex.quote(script),
            timeout=20,
        )
        if result.returncode:
            raise RuntimeError("host_control connection failed")
        try:
            facts = json.loads(result.stdout)
        except ValueError as exc:
            raise RuntimeError("host_control returned invalid host facts") from exc
        if not isinstance(facts, dict) or not facts.get("home"):
            raise RuntimeError("host_control returned incomplete host facts")
        return facts

    def check_connection(self) -> HostActionResult:
        result = self._run("/usr/bin/true", timeout=20)
        return HostActionResult(
            ok=result.returncode == 0,
            error_code=None if result.returncode == 0 else "ssh_unavailable",
            evidence={
                "transport": "ssh",
                "host": self._host,
                "user": self._user,
                "executor_materialized": result.returncode == 0,
            },
        )

    def check_terminal_bridge(self) -> HostActionResult:
        ok, evidence, error_code = verify_terminal_bridge(
            self._run,
        )
        return HostActionResult(
            ok=ok,
            error_code=error_code,
            evidence=evidence,
        )

    def read_text(self, path: str) -> str | None:
        script = (
            "import base64,pathlib,sys;"
            "p=pathlib.Path(sys.argv[1]);"
            "print(base64.b64encode(p.read_bytes()).decode() if p.exists() else '')"
        )
        result = self._run(
            "python3 -c "
            + shlex.quote(script)
            + " "
            + shlex.quote(path),
        )
        if result.returncode:
            raise RuntimeError("host_control file read failed")
        encoded = result.stdout.strip()
        return (
            base64.b64decode(encoded).decode("utf-8")
            if encoded else None
        )

    def write_text(self, path: str, content: str) -> None:
        script = (
            "import base64,pathlib,sys;"
            "p=pathlib.Path(sys.argv[1]);p.parent.mkdir(parents=True,exist_ok=True);"
            "p.write_bytes(base64.b64decode(sys.stdin.read()))"
        )
        result = self._run(
            "python3 -c "
            + shlex.quote(script)
            + " "
            + shlex.quote(path),
            input_text=base64.b64encode(content.encode("utf-8")).decode("ascii"),
        )
        if result.returncode:
            raise RuntimeError("host_control file write failed")

    def probe_path(self, surface: str) -> Sequence[str]:
        flag = "-lic" if surface == "login" else "-c"
        probe = "printf '%s' \"$PATH\""
        result = self._run(
            f"{shlex.quote(self.shell)} {flag} {shlex.quote(probe)}",
            timeout=20,
        )
        if result.returncode:
            raise RuntimeError(f"host_control {surface} PATH probe failed")
        return tuple(entry for entry in result.stdout.strip().split(":") if entry)

    def run_machine_assertions(
        self,
        assertions: Sequence[Mapping[str, Any]],
    ) -> HostActionResult:
        rows: list[dict[str, Any]] = []
        for assertion in assertions:
            argv = [str(value) for value in assertion["argv"]]
            expected = int(assertion.get("expected_exit", 0))
            result = self._run(" ".join(shlex.quote(value) for value in argv))
            rows.append({
                "argv": argv,
                "expected_exit": expected,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            })
            if result.returncode != expected:
                return HostActionResult(
                    False,
                    {"assertions": rows, "secret_scan": "pending-redaction"},
                    "machine_assertion_failed",
                )
        return HostActionResult(
            True,
            {"assertions": rows, "secret_scan": "passed-after-redaction"},
        )

    def run_terminal_case(
        self,
        *,
        entry_surface: str,
        required_completion: str,
        steps: Sequence[Mapping[str, Any]],
        capture_checkpoints: Sequence[str],
    ) -> HostActionResult:
        session = "yoke-qa-" + uuid4().hex[:12]
        evidence_root = (
            machine_config.yoke_home()
            / "qa-host-control"
            / session
        )
        evidence_root.mkdir(parents=True, exist_ok=True)
        captured: list[dict[str, Any]] = []
        matched: list[str] = []
        degraded: list[str] = []
        try:
            start = (
                f"tmux new-session -d -s {shlex.quote(session)} "
                + shlex.quote(entry_surface)
            )
            if self._run(start).returncode:
                return HostActionResult(
                    False,
                    {"entry_surface_started": False},
                    "terminal_entry_failed",
                )
            attach = f"tmux attach-session -t {session}"
            apple = (
                'tell application "Terminal" to do script '
                + json.dumps(attach)
            )
            if self._run(
                "/usr/bin/osascript -e " + shlex.quote(apple)
            ).returncode:
                return HostActionResult(
                    False,
                    {"entry_surface_started": True, "terminal_attached": False},
                    "terminal_attach_failed",
                )
            for step in steps:
                sent = str(step.get("send") or "")
                if sent:
                    command = (
                        f"tmux send-keys -t {shlex.quote(session)} -- "
                        + shlex.quote(sent)
                    )
                    if self._run(command).returncode:
                        return HostActionResult(
                            False,
                            {"steps": captured},
                            "terminal_input_failed",
                        )
                transcript = wait_for_text(
                    self._run,
                    session=session,
                    expected=str(step["expect"]),
                    timeout_seconds=int(step.get("timeout_seconds", 30)),
                )
                key = str(step["key"])
                reached = transcript is not None
                captured.append({
                    "key": key,
                    "expect": str(step["expect"]),
                    "reached": reached,
                    "transcript": transcript or "",
                })
                if not reached:
                    return HostActionResult(
                        False,
                        {"steps": captured},
                        (
                            "terminal_completion_not_reached"
                            if key == required_completion
                            else "terminal_checkpoint_failed"
                        ),
                    )
                matched.append(key)
                if key in capture_checkpoints:
                    screenshot = capture_screen(
                        self._run,
                        session=session,
                        key=key,
                        evidence_root=evidence_root,
                    )
                    if screenshot is None:
                        degraded.append(f"{key}: screenshot capture blocked")
                    else:
                        captured[-1]["artifact_handle"] = local_handle(
                            str(screenshot.resolve()),
                            "image/png",
                        )
            if required_completion not in matched:
                return HostActionResult(
                    False,
                    {"steps": captured, "required_completion": required_completion},
                    "terminal_completion_not_reached",
                )
            return HostActionResult(
                True,
                {
                    "steps": captured,
                    "required_completion": required_completion,
                    "capture_degraded_reason": "; ".join(degraded) or None,
                },
            )
        finally:
            self._run(
                f"tmux kill-session -t {shlex.quote(session)}",
                timeout=10,
            )

def register_ssh_mac_host_control() -> None:
    """Install the core-approved machine-local adapter factory."""
    register_host_control_factory(SshMacHostControl)


__all__ = [
    "SSH_OPTIONS",
    "SshMacHostControl",
    "register_ssh_mac_host_control",
]
