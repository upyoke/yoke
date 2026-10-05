"""A detached final CLI removal that cannot race the running uninstall."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from yoke_contracts.process_ancestry import process_start_time


@dataclass
class Handoff:
    arm_file: Path
    log: Path
    process: subprocess.Popen

    def arm(self) -> None:
        self.arm_file.write_text("armed", encoding="utf-8")

    def cancel(self) -> None:
        self.process.terminate()
        self.process.wait(timeout=10)


def prepare() -> Handoff:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError(
            "uninstall_uv_missing: restore uv on PATH and retry uninstall."
        )
    parent = os.getpid()
    started = process_start_time(parent)
    if not started:
        raise RuntimeError(
            "uninstall_parent_identity_missing: cannot safely detach; repair process inspection and retry."
        )
    directory = Path(tempfile.mkdtemp(prefix="yoke-uninstall-"))
    script = directory / "finish.py"
    script.write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    log = directory / "result.log"
    arm_file = directory / "armed"
    ready_file = directory / "ready"
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                str(script),
                str(parent),
                started,
                uv,
                str(arm_file),
                str(ready_file),
            ],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=directory,
        )
    deadline = time.monotonic() + 10
    while not ready_file.is_file():
        if process.poll() is not None or time.monotonic() >= deadline:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            raise RuntimeError(
                f"uninstall_cli_handoff_failed: detached worker did not start; "
                f"inspect {log}, repair its reported problem and retry uninstall."
            )
        time.sleep(0.05)
    return Handoff(arm_file, log, process)


def finish(parent: int, started: str, uv: str, arm_file: Path, ready_file: Path) -> int:
    # Import all code needed before uv removes the running interpreter's venv.
    ready_file.write_text("ready", encoding="utf-8")
    while _parent_running(parent, started):
        time.sleep(0.1)
    if not arm_file.is_file():
        print("CLI: skipped (main uninstall did not complete cleanup)", flush=True)
        return 1
    try:
        result = subprocess.run(
            [uv, "tool", "uninstall", "yoke-cli"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(
            f"CLI: failed (uninstall_cli_failed: {type(exc).__name__}; run uv tool uninstall yoke-cli)",
            flush=True,
        )
        return 1
    if result.returncode:
        print(
            "CLI: failed (uninstall_cli_failed: uv tool uninstall yoke-cli "
            f"exited {result.returncode}; repair uv and rerun that command)",
            flush=True,
        )
        print(result.stderr or result.stdout, flush=True)
        return 1
    print("CLI: done (uv tool uninstall yoke-cli)", flush=True)
    return 0


def _parent_running(parent: int, started: str) -> bool:
    current = process_start_time(parent)
    if current is not None:
        return current == started
    # An unavailable process snapshot is not proof of death.
    try:
        os.kill(parent, 0)
    except ProcessLookupError:
        return False
    return True


if __name__ == "__main__":
    sys.exit(
        finish(
            int(sys.argv[1]),
            sys.argv[2],
            sys.argv[3],
            Path(sys.argv[4]),
            Path(sys.argv[5]),
        )
    )
