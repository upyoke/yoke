"""Publish immutable CLI environments and lease them while commands run.

The installed launcher is a standalone copy, interpreted by uv's base Python;
it can choose and protect a release before importing any release-owned code.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

INSTALL_ROOT = None
RECOVERY = "rerun the public installer or yoke update to repair the CLI"
RELEASE_ENTRY = """
import os, signal, sys, threading
def end_with_launcher(fd):
    while os.read(fd, 1):
        pass
    os.kill(os.getpid(), signal.SIGTERM)
threading.Thread(target=end_with_launcher, args=(int(sys.argv[2]),), daemon=True).start()
try:
    from yoke_cli.config.install_binding import detect
    binding = detect()
    if binding['kind'] != 'packaged_wheel' or not binding['version']:
        sys.exit('released_cli_required: CLI must be a versioned wheel; ' + sys.argv[1])
    from yoke_cli.main import main
except (ImportError, OSError) as exc:
    sys.exit('released_cli_unavailable: ' + str(exc) + '; ' + sys.argv[1])
sys.exit(main(sys.argv[3:]) or 0)
"""


@contextmanager
def locked(path: Path, *, shared: bool = False, nonblocking: bool = False):
    with path.open("a+") as handle:
        mode = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
        try:
            fcntl.flock(handle, mode | fcntl.LOCK_NB)
        except BlockingIOError:
            if nonblocking:
                raise
            print(
                "Waiting by design: CLI publication lock; checking every 50ms; gives up after 30 seconds.",
                file=sys.stderr,
            )
            deadline = time.monotonic() + 30
            while True:
                try:
                    fcntl.flock(handle, mode | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "cli_publication_busy: let the active update finish, then retry"
                        ) from None
                    time.sleep(0.05)
        try:
            yield handle
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def _launcher_pipe():
    """A pipe only this process holds open, for RELEASE_ENTRY's ``fd`` argument.

    The released command waits on its read end; end of file means this process
    is gone, however it was stopped, so the command ends too rather than running
    on with its locks.
    """
    alive, held = os.pipe()
    try:
        yield alive
    finally:
        os.close(alive)
        os.close(held)


def _replace(path: Path, content: str, *, executable: bool = False) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
            if executable:
                os.fchmod(output.fileno(), 0o755)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _point(path: Path, target: Path) -> None:
    temporary = path.with_name(f".{path.name}-{os.getpid()}")
    try:
        temporary.symlink_to(target)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _generation(root: Path) -> Path:
    generation = (root / "current").resolve(strict=True)
    if generation.parent != root / "releases":
        raise RuntimeError(
            "cli_release_target_invalid: current points outside releases"
        )
    return generation


def exec_current_python(arguments: list[str]) -> int:
    """Replace a resident under the publication lock, keeping its start lock."""
    try:
        environment = Path(sys.executable).parent.parent.resolve()
        generation = environment.parent.parent
        immutable = (
            environment.name == "yoke-cli"
            and environment.parent.name == "tools"
            and generation.parent.name == "releases"
        )
        root = generation.parent.parent
        with (
            locked(root / "publication.lock", shared=True)
            if immutable
            else nullcontext()
        ):
            # Resolve the generation, never the virtualenv's Python symlink.
            python = (
                _generation(root) / "tools/yoke-cli/bin/python3"
                if immutable
                else Path(sys.executable)
            )
            os.execv(str(python), [str(python), *arguments])
    except (OSError, RuntimeError) as exc:
        print(
            f"hook_resident_restart_failed: {exc}; {RECOVERY}, then run "
            "yoke hook resident restart from your own terminal; read this evaluator log",
            file=sys.stderr,
        )
        return 2
    return 0


def _process_commands() -> str:
    result = subprocess.run(
        ["ps", "-wwaxo", "pid=,command="], capture_output=True, text=True, timeout=10
    )
    if result.returncode or not result.stdout.strip():
        raise RuntimeError(
            "cli_cleanup_process_snapshot_unavailable: restore ps and retry the update"
        )
    return result.stdout


def collect(root: Path, *, legacy: bool = False, pending_safe: bool = False) -> None:
    """Called under the publication lock; absence of a lease alone is insufficient.

    Process inspection also protects direct interpreter children and the original
    uv environment, whose commands started before release leases existed.
    """
    root = root.resolve()
    current = _generation(root)
    commands = _process_commands()
    for candidate in (root / "releases").iterdir():
        if candidate == current or candidate.is_symlink() or not candidate.is_dir():
            continue
        if str(candidate) in commands or (
            (candidate / "pending").exists() and not pending_safe
        ):
            continue
        try:
            with locked(candidate / "lease", nonblocking=True):
                shutil.rmtree(candidate)
        except BlockingIOError:
            continue
    original = root.parent / "yoke-cli"
    if legacy and original.is_dir() and not original.is_symlink():
        if str(original) not in commands:
            shutil.rmtree(original)
            (root / "retire-original").unlink(missing_ok=True)


def activate(root: Path, generation: Path, bin_dir: Path, version: str) -> None:
    root = root.resolve()
    generation = generation.resolve()
    if generation.parent != root / "releases":
        raise RuntimeError(
            "cli_release_target_invalid: candidate must be inside releases"
        )
    executable = generation / "tools" / "yoke-cli" / "bin" / "yoke"
    # Probe and repair with the candidate, while the public launcher still uses
    # the previous release. A broken candidate never replaces that launcher.
    for arguments in (
        ["--version"],
        ["--help"],
        ["github", "credential-helper", "refresh", "--json"],
    ):
        with _launcher_pipe() as alive:
            result = subprocess.run(
                [
                    str(executable.with_name("python3")),
                    "-I",
                    "-c",
                    RELEASE_ENTRY,
                    RECOVERY,
                    str(alive),
                    *arguments,
                ],
                pass_fds=(alive,),
                capture_output=True,
                text=True,
                timeout=120,
            )
        if result.returncode:
            raise RuntimeError(
                f"cli_candidate_verification_failed: {result.stderr or result.stdout}"
            )
        if arguments == ["--version"] and result.stdout.strip() != version:
            raise RuntimeError(
                "cli_candidate_version_mismatch: candidate does not report the requested release"
            )
        if arguments[0] == "github":
            receipt = json.loads(result.stdout)
            if (
                not isinstance(receipt, dict)
                or "configured" not in receipt
                or receipt.get("error")
            ):
                raise RuntimeError(
                    "cli_candidate_helper_repair_failed: no successful credential-helper receipt"
                )
    (generation / "lease").touch()
    # Resolve the base interpreter, not the version-owned virtualenv symlink.
    python = Path(sys._base_executable).resolve()
    source = Path(__file__).read_text(encoding="utf-8")
    source = source.replace("INSTALL_ROOT = None", f"INSTALL_ROOT = {str(root)!r}", 1)
    source = f"#!{python}\n" + source
    bin_dir.mkdir(parents=True, exist_ok=True)
    with locked(root / "publication.lock"):
        _replace(root / "launcher", source, executable=True)
        current = root / "current"
        previous = current.resolve(strict=True) if current.exists() else None
        try:
            _point(current, generation)
            _point(bin_dir / "yoke", root / "launcher")
        except OSError:
            if previous is None:
                current.unlink(missing_ok=True)
            else:
                _point(current, previous)
            raise
        if (root.parent / "yoke-cli").is_dir():
            (root / "retire-original").touch()
        (generation / "pending").unlink(missing_ok=True)
        try:
            collect(root, legacy=True, pending_safe=True)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            print(
                f"cli_cleanup_deferred: {exc}; retry yoke update after old commands finish",
                file=sys.stderr,
            )


def launch(root: Path, arguments: list[str]) -> int:
    lease = None
    try:
        with locked(root / "publication.lock", shared=True):
            generation = _generation(root)
            lease = (generation / "lease").open("a+")
            fcntl.flock(lease, fcntl.LOCK_SH)
        python = generation / "tools" / "yoke-cli" / "bin" / "python3"
        with _launcher_pipe() as alive:
            result = subprocess.run(
                [str(python), "-I", "-c", RELEASE_ENTRY, RECOVERY, str(alive)]
                + arguments,
                pass_fds=(lease.fileno(), alive),
            )
        return result.returncode if result.returncode >= 0 else 128 - result.returncode
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError) as exc:
        print(f"cli_release_unavailable: {exc}; {RECOVERY}", file=sys.stderr)
        return 2
    finally:
        if lease is not None:
            lease.close()
            try:
                with locked(root / "publication.lock", nonblocking=True):
                    if (
                        _generation(root) != generation
                        or (root / "retire-original").exists()
                    ):
                        collect(root, legacy=True)
            except BlockingIOError:
                pass
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                print(
                    f"cli_cleanup_deferred: {exc}; retry yoke update after old commands finish",
                    file=sys.stderr,
                )


def uninstall(root: Path, bin_dir: Path) -> None:
    """Remove only this install's launcher and released environments."""
    from contextlib import ExitStack

    root = root.resolve()
    with ExitStack() as stack:
        stack.enter_context(locked(root / "publication.lock", nonblocking=True))
        _generation(root)
        commands = "\n".join(
            line
            for line in _process_commands().splitlines()
            if line.split(maxsplit=1)[0] != str(os.getpid())
        )
        original = root.parent / "yoke-cli"
        if str(root / "releases") in commands or str(original) in commands:
            raise BlockingIOError("CLI interpreter still running")
        for candidate in (root / "releases").iterdir():
            stack.enter_context(locked(candidate / "lease", nonblocking=True))
        launcher = bin_dir / "yoke"
        if launcher.is_symlink() and launcher.resolve() == root / "launcher":
            launcher.unlink()
        shutil.rmtree(root)
        if original.is_dir() and not original.is_symlink():
            shutil.rmtree(original)


def main() -> int:
    if INSTALL_ROOT is not None:
        return launch(Path(INSTALL_ROOT), sys.argv[1:])
    try:
        root, generation, bin_dir, version = sys.argv[1:]
        activate(Path(root), Path(generation), Path(bin_dir), version)
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"cli_release_activation_failed: {exc}; {RECOVERY}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
