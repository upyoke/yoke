"""Captured, named command execution for the disposable-runner product smoke."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


def venv_executable(venv: Path, name: str) -> Path:
    """A console script or interpreter inside a venv on this OS."""
    if os.name == "nt":
        return venv / "Scripts" / f"{name}.exe"
    return venv / "bin" / name


class SmokeFailure(RuntimeError):
    """A smoke assertion failed; its named capture carries recovery evidence."""


class Commands:
    def __init__(self, output: Path, env: dict[str, str]):
        self.output, self.env = output, env
        self.sequence = 0
        self.step = "runner-identity"
        self.capture = output / "report.json"

    def failure(self, reason, detail):
        return SmokeFailure(
            f"{reason}: step={self.step}: {detail}; inspect {self.capture}, "
            "correct the named step and rerun the plan"
        )

    def run(self, name, command, *, cwd, stdin=None, accepted=(0,), shell=False):
        self.sequence += 1
        capture = self.output / f"{self.sequence:02d}-{name}.txt"
        self.step, self.capture = name, capture
        print(f"product-smoke step={name} capture={capture}", flush=True)
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=self.env,
                input=stdin,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=900,
                shell=shell,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            capture.write_text(str(exc), encoding="utf-8")
            reason = (
                "command_timeout"
                if isinstance(exc, subprocess.TimeoutExpired)
                else "command_start_failed"
            )
            raise self.failure(reason, str(exc)) from exc
        capture.write_text(
            f"command={command!r}\nexit_code={result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            encoding="utf-8",
        )
        if result.returncode not in accepted:
            raise self.failure("command_failed", f"exit={result.returncode}")
        return result

    def parse_json(self, stdout):
        try:
            payload = json.loads(stdout)
            if not isinstance(payload, dict):
                raise ValueError("expected a JSON object")
        except ValueError as exc:
            raise self.failure("command_json_invalid", str(exc)) from exc
        return payload

    def document(self, name, command, *, cwd):
        payload = self.parse_json(self.run(name, command, cwd=cwd).stdout)
        if payload.get("success") is False:
            raise self.failure("command_refused", payload.get("error"))
        return payload.get("result", payload)
