"""A detached final CLI removal that cannot race the running uninstall.

The finisher is a copy of this file run by uv's base Python with ``-I``, so
it holds no file of the tool environment it deletes open (Windows refuses to
delete a running executable or a loaded extension). It imports only stdlib
plus pure-Python Yoke modules read from the release's package roots, then
waits for the uninstall process to exit by taking a lock that process holds.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

LOCK_NAME = "parent.lock"


@dataclass
class Handoff:
    arm_file: Path
    log: Path
    process: subprocess.Popen
    lock_descriptor: int

    def arm(self) -> None:
        self.arm_file.write_text("armed", encoding="utf-8")

    def cancel(self) -> None:
        self.process.terminate()
        self.process.wait(timeout=10)
        os.close(self.lock_descriptor)


def temp_root(home: Path) -> Path:
    """Return the OS temp directory, refusing one this uninstall deletes."""
    root = Path(tempfile.gettempdir()).resolve()
    resolved = home.resolve()
    if root == resolved or resolved in root.parents:
        raise RuntimeError(
            f"uninstall_temp_inside_home: the temporary directory {root} is inside "
            f"the machine home {home}, which uninstall deletes. Set TMPDIR (TEMP "
            "and TMP on Windows) to a directory outside it and retry uninstall."
        )
    return root


def prepare(home: Path) -> Handoff:
    from yoke_contracts import platform_file_lock

    root = temp_root(home)
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError(
            "uninstall_uv_missing: restore uv on PATH and retry uninstall."
        )
    tools, bin_dir = (_uv_directory(uv, args) for args in (["dir"], ["dir", "--bin"]))
    directory = Path(tempfile.mkdtemp(prefix="yoke-uninstall-", dir=root))
    script = directory / "finish.py"
    script.write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    log = directory / "result.log"
    arm_file = directory / "armed"
    ready_file = directory / "ready"
    lock = directory / LOCK_NAME
    # Held until this process exits; the finisher's wait for it is the parent wait.
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    platform_file_lock.acquire_exclusive_nonblocking(descriptor)
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [
                _base_python(),
                "-I",
                str(script),
                str(lock),
                str(arm_file),
                str(ready_file),
                str(tools / "yoke-cli-releases"),
                str(bin_dir),
                *_package_roots(),
            ],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            cwd=directory,
            **_detached(),
        )
    deadline = time.monotonic() + 10
    while not ready_file.is_file():
        if process.poll() is not None or time.monotonic() >= deadline:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
            os.close(descriptor)
            raise RuntimeError(
                f"uninstall_cli_handoff_failed: detached worker did not start; "
                f"inspect {log}, repair its reported problem and retry uninstall."
            )
        time.sleep(0.05)
    return Handoff(arm_file, log, process, descriptor)


def _uv_directory(uv: str, arguments: list[str]) -> Path:
    try:
        result = subprocess.run(
            [uv, "tool", *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            f"uninstall_uv_failed: uv tool {' '.join(arguments)}: {exc}; "
            "repair uv and retry uninstall."
        ) from exc
    directory = Path(result.stdout.strip())
    if not directory.is_absolute():
        raise RuntimeError(
            f"uninstall_uv_failed: uv tool {' '.join(arguments)} returned no "
            "absolute directory; repair uv and retry uninstall."
        )
    return directory


def _base_python() -> str:
    """The interpreter behind the tool venv, which uv tool uninstall keeps."""
    return sys._base_executable


def _package_roots() -> list[str]:
    """Import roots of the pure-Python modules the finisher needs."""
    import yoke_cli
    import yoke_contracts

    roots = (Path(module.__file__).parents[1] for module in (yoke_cli, yoke_contracts))
    return list(dict.fromkeys(str(root) for root in roots))


def _detached() -> dict:
    """Popen options that let the finisher outlive this process and its console."""
    if os.name == "nt":
        return {
            "creationflags": subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
        }
    return {"start_new_session": True}


def finish(
    lock: Path, arm_file: Path, ready_file: Path, root: Path, bin_dir: Path
) -> int:
    # Import everything before the parent exits and this removes the release.
    from yoke_cli.config.cli_release_runtime import uninstall
    from yoke_contracts import platform_file_lock
    from yoke_contracts.shell_path_state import remove_shell_path

    descriptor = os.open(lock, os.O_RDWR)
    ready_file.write_text("ready", encoding="utf-8")
    # The uninstall process holds this lock until it exits, on every OS.
    platform_file_lock.acquire_exclusive(descriptor)
    if not arm_file.is_file():
        print("CLI: skipped (main uninstall did not complete cleanup)", flush=True)
        return 1
    print(
        "Waiting by design: CLI commands must release their environments; checking file locks; gives up after 10 seconds.",
        flush=True,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                uninstall(root, bin_dir)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "cli_release_in_use: let running CLI commands finish, then retry uninstall"
                    ) from None
                time.sleep(0.1)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(
            f"CLI: failed (uninstall_cli_failed: {exc}; repair the reported problem and retry yoke uninstall)",
            flush=True,
        )
        return 1
    print("CLI: done (removed immutable CLI releases and launcher)", flush=True)
    # The PATH entry stays while the CLI does, so a failed run keeps `yoke` reachable.
    try:
        changed = remove_shell_path()
    except OSError as exc:
        print(f"shell PATH: failed ({exc})", flush=True)
        return 1
    print(
        f"shell PATH: done ({', '.join(changed) or 'no Yoke PATH blocks'})", flush=True
    )
    return 0


if __name__ == "__main__":
    sys.path[:0] = sys.argv[6:]
    sys.exit(finish(*(Path(value) for value in sys.argv[1:6])))
