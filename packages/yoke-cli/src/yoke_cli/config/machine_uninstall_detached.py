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
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

HANDOFF_PREFIX = "yoke-uninstall-"

LOCK_NAME = "parent.lock"


@dataclass
class Handoff:
    arm_file: Path
    log: Path
    process: subprocess.Popen
    lock_descriptor: int
    releases: Path

    def arm(self) -> None:
        self.arm_file.write_text("armed", encoding="utf-8")

    def cancel(self) -> None:
        try:
            self.process.terminate()
            self.process.wait(timeout=10)
            os.close(self.lock_descriptor)
            shutil.rmtree(self.log.parent)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                f"uninstall_handoff_cleanup_failed: {exc}; once the detached worker "
                f"has stopped, delete {self.log.parent} and retry uninstall."
            ) from exc


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
    releases = tools / "yoke-cli-releases"
    directory = Path(tempfile.mkdtemp(prefix=HANDOFF_PREFIX, dir=root))
    script = directory / "finish.py"
    script.write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    log = directory / "result.log"
    arm_file = directory / "armed"
    ready_file = directory / "ready"
    lock = directory / LOCK_NAME
    # Held until this process exits; the finisher's wait for it is the parent wait.
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    platform_file_lock.acquire_exclusive_nonblocking(descriptor)
    output = log.open("w", encoding="utf-8")
    try:
        with output:
            process = subprocess.Popen(
                [
                    _base_python(),
                    "-I",
                    str(script),
                    str(lock),
                    str(arm_file),
                    str(ready_file),
                    str(releases),
                    str(bin_dir),
                    *_package_roots(),
                ],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                # Outside the folder, so the worker can delete it when done.
                cwd=root,
                **_detached(),
            )
    except PermissionError as exc:
        os.close(descriptor)
        shutil.rmtree(directory)
        if os.name != "nt":
            raise
        raise RuntimeError(
            "uninstall_cli_handoff_failed: this process runs in a Windows job "
            "that forbids breakaway, so a detached CLI removal would be killed "
            "with it; after this uninstall exits, remove the releases by hand: "
            f"{manual_removal(releases)}"
        ) from exc
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
    return Handoff(arm_file, log, process, descriptor, releases)


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
    """Popen options that let the finisher outlive this process and its console.

    Windows OpenSSH ends a session's kill-on-close job when the session closes,
    so the finisher leaves the job. The flag has no effect outside a job.
    """
    if os.name == "nt":
        return {
            "creationflags": subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.CREATE_BREAKAWAY_FROM_JOB
        }
    return {"start_new_session": True}


def manual_removal(root: Path | str) -> str:
    """A shell command that removes the CLI releases without ``yoke``."""
    if os.name == "nt":
        target = str(root) if str(root).startswith("\\\\?\\") else f"\\\\?\\{root}"
        return "Remove-Item -LiteralPath '{}' -Recurse -Force".format(target.replace("'", "''"))
    return f"rm -rf {shlex.quote(str(root))}"


def finish(
    lock: Path, arm_file: Path, ready_file: Path, root: Path, bin_dir: Path
) -> int:
    # Import everything before the parent exits and this removes the release.
    from yoke_cli.config.cli_release_runtime import uninstall
    from yoke_contracts import platform_file_lock
    from yoke_contracts.shell_startup_files import remove_shell_path

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
            f"CLI: failed (uninstall_cli_failed: {exc}; `yoke` may be gone, so once no "
            f"CLI command runs, remove the releases by hand: {manual_removal(root)})",
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
    # Success needs no recovery evidence: remove this worker's own folder.
    os.close(descriptor)
    if lock.parent.name.startswith(HANDOFF_PREFIX):
        _remove_own_folder(lock.parent)
    return 0


def _remove_own_folder(folder: Path) -> None:
    """Delete the handoff folder, holding no file or directory inside it.

    Windows cannot delete an open file or a process's working directory, and
    this worker's stdout and stderr are the folder's result.log. A failure is
    appended to that log, which then stays for the operator to read.
    """
    os.chdir(folder.parent)
    _release_log()
    try:
        shutil.rmtree(folder)
    except OSError as exc:
        with (folder / "result.log").open("a", encoding="utf-8") as log:
            log.write(
                f"handoff folder: failed (uninstall_handoff_cleanup_failed: {exc}); "
                f"delete {folder} once no process holds it\n"
            )


def _release_log() -> None:
    """Point stdout and stderr away from result.log so its handle closes."""
    sys.stdout.flush()
    sys.stderr.flush()
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
    finally:
        os.close(devnull)


if __name__ == "__main__":
    sys.path[:0] = sys.argv[6:]
    sys.exit(finish(*(Path(value) for value in sys.argv[1:6])))
