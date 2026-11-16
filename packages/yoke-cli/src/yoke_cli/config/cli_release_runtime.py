"""Publish immutable CLI releases with a standalone stdlib launcher.

Pointer files and shims select current; leases retain running releases.
"""

from __future__ import annotations

from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time

WINDOWS = os.name == "nt"
if WINDOWS:
    import msvcrt
else:
    import fcntl

INSTALL_ROOT = None
RECOVERY = "rerun the public installer or yoke update to repair the CLI"
PROBES = (["--version"], ["--help"], "github credential-helper refresh --check-only --json".split())
WAIT_NOTICE = "Waiting by design: CLI publication lock; checking every 50ms; gives up after 30 seconds."
BUSY = "cli_publication_busy: let the active update finish, then retry"
RESTART = f"{RECOVERY}, then run yoke hook resident restart from your own terminal; read this evaluator log"
HELD = []  # Leases this process keeps until it exits.
CLEANUP_RETRY = "the next yoke command or update retries cleanup"
RELEASE_ENTRY = """
import os, signal, sys, threading
def end_with_launcher(token):
    if os.name == 'nt':
        import msvcrt; token = msvcrt.open_osfhandle(token, os.O_RDONLY)
    try:
        while os.read(token, 1): pass
    except OSError: pass
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
ENTRY = ["-I", "-c", RELEASE_ENTRY, RECOVERY]


@contextmanager
def locked(path: Path, *, nonblocking: bool = False):
    """Hold an exclusive lock on ``path``, waiting up to 30 seconds."""
    with path.open("a+", encoding="utf-8") as handle:
        handle.seek(0)  # Windows locks a byte range from the file position.
        deadline = time.monotonic() + 30
        if not _try_lock(handle):
            if nonblocking:
                raise BlockingIOError(f"lock held by another process: {path}")
            print(WAIT_NOTICE, file=sys.stderr)
            while not _try_lock(handle):
                if time.monotonic() >= deadline:
                    raise RuntimeError(BUSY)
                time.sleep(0.05)
        try:
            yield handle
        finally:  # Closing releases a POSIX lock; Windows asks for an unlock.
            if WINDOWS:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _try_lock(handle) -> bool:
    try:
        if WINDOWS:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except PermissionError if WINDOWS else BlockingIOError:
        return False
    return True


def release_python(generation: Path) -> Path:
    """The interpreter of the uv tool environment inside a release folder."""
    environment = generation / "tools" / "yoke-cli"
    if WINDOWS:
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python3"


def _generation(root: Path) -> Path:
    name = (root / "current").read_text(encoding="utf-8").strip()
    if not name or name != Path(name).name or name.startswith("."):
        raise RuntimeError("cli_release_target_invalid: current names no release")
    return root / "releases" / name


def _lease(generation: Path):
    """Open a release's lease for as long as this process uses the release."""
    lease = (generation / "lease").open("r", encoding="utf-8")
    if not WINDOWS:  # Cleanup may have retired it while the lock waited.
        fcntl.flock(lease, fcntl.LOCK_SH)
        if os.fstat(lease.fileno()).st_ino != (generation / "lease").stat().st_ino:
            lease.close()
            raise FileNotFoundError(f"release retired while starting: {generation}")
    return lease


@contextmanager
def _launcher_pipe(lease):
    """A pipe RELEASE_ENTRY watches: end of file means the launcher stopped."""
    alive, held = os.pipe()
    try:
        if WINDOWS:
            handle = msvcrt.get_osfhandle(alive)
            os.set_handle_inheritable(handle, True)
            info = subprocess.STARTUPINFO(lpAttributeList={"handle_list": [handle]})
            yield str(handle), {"startupinfo": info}
        else:
            kept = (alive,) if lease is None else (alive, lease.fileno())
            yield str(alive), {"pass_fds": kept}
    finally:
        os.close(alive)
        os.close(held)


def _replace(path: Path, content: str, *, executable: bool = False) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
            output.write(content)
            if executable and not WINDOWS:
                os.fchmod(output.fileno(), 0o755)
            output.flush()
            os.fsync(output.fileno())
        for attempt in range(100):  # Windows: a reader may hold it open briefly.
            try:
                return os.replace(temporary, path)
            except PermissionError:
                if not WINDOWS or attempt == 99:
                    raise
                time.sleep(0.02)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _shims(root: Path, python: Path, bin_dir: Path) -> dict[Path, str]:
    launcher = root / "launcher"
    if WINDOWS and any(mark in f"{python}{launcher}" for mark in '%"'):
        raise RuntimeError(f"cli_launcher_path_unsupported: % or quote in {launcher}")
    run = "#!/bin/sh\nexec " + shlex.join([python.as_posix(), launcher.as_posix()])
    shims = {bin_dir / "yoke": f'{run} "$@"\n'}
    shims[root / "python"] = f'{run} --python "$@"\n'
    if WINDOWS:
        shims[bin_dir / "yoke.cmd"] = f'@"{python}" "{launcher}" %*\r\n'
    return shims


def _remove_tree(path: Path) -> None:
    def clear_read_only(function, failed, _error):
        os.chmod(failed, stat.S_IWRITE)
        function(failed)

    hook = "onexc" if sys.version_info >= (3, 12) else "onerror"
    shutil.rmtree(path, **{hook: clear_read_only})


def _retire(release: Path, retired: Path) -> bool:
    """Rename an unused release out of ``releases``; False while it is in use."""
    retired.mkdir(exist_ok=True)
    target = retired / f"{release.name}-{os.getpid()}-{time.monotonic_ns()}"
    try:
        if WINDOWS:
            release.rename(target)
        else:
            with locked(release / "lease", nonblocking=True):
                release.rename(target)
    except (BlockingIOError, PermissionError):
        return False
    return True


def collect(root: Path, *, pending_safe: bool = False) -> None:
    """Retire unused releases under the publication lock; ``pending`` marks an
    install in progress, except after a publication (``pending_safe``)."""
    root = root.resolve()
    current = _generation(root)
    for candidate in (root / "releases").iterdir():
        pending = (candidate / "pending").exists() and not pending_safe
        if candidate != current and candidate.is_dir() and not pending:
            _retire(candidate, root / "retired")
    for retired in (root / "retired").glob("*"):
        _remove_tree(retired)


def hold_release(*, current: bool = False):
    from yoke_cli.config.cli_release_resident import hold_release as run

    return run(current=current)


def exec_current_python(arguments: list[str]):
    from yoke_cli.config.cli_release_resident import exec_current_python as run

    return run(arguments)


def _probe(generation: Path, version: str) -> None:
    command = [str(release_python(generation)), *ENTRY]
    for arguments in PROBES:
        with _launcher_pipe(None) as (token, options):
            options.update(capture_output=True, text=True, timeout=120)
            result = subprocess.run([*command, token, *arguments], **options)
        if result.returncode:
            raise RuntimeError(
                f"cli_candidate_verification_failed: {result.stderr or result.stdout}"
            )
        if arguments == ["--version"] and result.stdout.strip() != version:
            raise RuntimeError("cli_candidate_version_mismatch: wrong version")
        if arguments[0] == "github":
            receipt = json.loads(result.stdout)
            failed = not isinstance(receipt, dict) or receipt.get("error")
            if failed or receipt.get("checked") is not True:
                raise RuntimeError(
                    f"cli_candidate_helper_check_failed: no successful credential-helper check; {RECOVERY}"
                )


def activate(root: Path, generation: Path, bin_dir: Path, version: str) -> None:
    root = root.resolve()
    generation = generation.resolve()
    if generation.parent != root / "releases":
        raise RuntimeError("cli_release_target_invalid: candidate outside releases")
    _probe(generation, version)
    (generation / "lease").touch()
    python = Path(sys._base_executable).resolve()
    source = Path(__file__).read_text(encoding="utf-8")
    source = source.replace("INSTALL_ROOT = None", f"INSTALL_ROOT = {str(root)!r}", 1)
    bin_dir.mkdir(parents=True, exist_ok=True)
    with locked(root / "publication.lock"), ExitStack() as cleanup:
        publication = {
            root / "launcher": source,
            **_shims(root, python, bin_dir),
            root / "current": generation.name + "\n",
        }
        previous = {}
        for path in publication:
            previous[path] = None
            if path.exists() or path.is_symlink():
                descriptor, name = tempfile.mkstemp(prefix=".publication-", dir=path.parent)
                os.close(descriptor)
                backup = Path(name)
                backup.unlink()
                cleanup.callback(backup.unlink, missing_ok=True)
                shutil.copy2(path, backup, follow_symlinks=False)
                previous[path] = backup
        written = []
        try:
            for path, content in publication.items():
                _replace(
                    path,
                    content,
                    executable=path not in (root / "launcher", root / "current"),
                )
                written.append(path)
            (generation / "pending").unlink(missing_ok=True)
        except OSError:
            for path in reversed(written):
                old = previous[path]
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    os.replace(old, path)
            raise
        try:
            collect(root, pending_safe=True)
        except OSError as exc:
            print(f"cli_cleanup_deferred: {exc}; {CLEANUP_RETRY}", file=sys.stderr)

def launch(root: Path, arguments: list[str]) -> int:
    """Run a command, or with ``--python`` the release's Python, in the current release."""
    generation = None
    try:
        for attempt in range(3):
            generation = _generation(root)
            python = str(release_python(generation))
            try:
                lease = _lease(generation)
                with _launcher_pipe(lease) as (token, options), lease:
                    command = [python, *arguments[1:]]
                    if arguments[:1] != ["--python"]:
                        command = [python, *ENTRY, token, *arguments]
                    result = subprocess.run(command, **options)
                break
            except FileNotFoundError:  # Cleanup retired it before it started.
                if attempt == 2:
                    raise
        return result.returncode if result.returncode >= 0 else 128 - result.returncode
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError) as exc:
        print(f"cli_release_unavailable: {exc}; {RECOVERY}", file=sys.stderr)
        return 2
    finally:  # The last command on a replaced release retires it.
        try:
            if generation is not None:
                with locked(root / "publication.lock", nonblocking=True):
                    if _generation(root) != generation:
                        collect(root)
        except BlockingIOError:
            pass
        except (OSError, RuntimeError) as exc:
            print(f"cli_cleanup_deferred: {exc}; {CLEANUP_RETRY}", file=sys.stderr)

def uninstall(root: Path, bin_dir: Path) -> None:
    """Remove this install's shims and releases; BlockingIOError while one runs."""
    root = root.resolve()
    with locked(root / "publication.lock", nonblocking=True):
        current = _generation(root)
        # Retire the current release last, so a refusal leaves a working CLI.
        for release in sorted((root / "releases").iterdir(), key=current.__eq__):
            if not _retire(release, root / "retired"):
                raise BlockingIOError(f"CLI release still running: {release}")
        launcher = root / "launcher"
        for shim in (bin_dir / "yoke", bin_dir / "yoke.cmd"):
            text = shim.read_text(encoding="utf-8", errors="replace") if shim.is_file() else ""
            if launcher.as_posix() in text or str(launcher) in text:
                shim.unlink()
    _remove_tree(root)

def main() -> int:
    """Frozen interface: installers run ``-m`` this with root generation bin_dir version."""
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
