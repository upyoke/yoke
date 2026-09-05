"""Create and retain the standing relay's physical Python identity."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import venv

from yoke_core.tools.session_relay_release import (
    RELAY_ACTIVE_RELEASE_NAME,
    RELAY_LAUNCH_LINK_NAME,
    RELAY_RELEASE_INSTALL_FAILED,
    RelayReleaseError,
    relay_active_release_path,
    relay_launch_path,
    relay_launch_targets_runtime,
    relay_runtime_path,
    relay_runtime_python,
)


RUNTIME_ENTRYPOINT_SOURCE = Path(__file__).with_name(
    "session_relay_runtime_entrypoint.py"
)

VenvCreator = Callable[[Path], None]


def ensure_relay_runtime(
    state_dir: Path,
    *,
    create_runtime: VenvCreator | None = None,
) -> Path:
    """Converge one physical runtime without replacing an existing Python."""
    runtime = relay_runtime_path(state_dir)
    launch = relay_launch_path(state_dir)
    if launch.is_symlink() and not relay_launch_targets_runtime(state_dir):
        _preserve_active_release(state_dir, launch.resolve(strict=True))
    if not runtime.exists():
        candidate = state_dir / f".{runtime.name}-{uuid.uuid4().hex}"
        try:
            (create_runtime or _create_runtime)(candidate)
            _validate_runtime(candidate)
            _install_runtime_entrypoint(candidate, state_dir=state_dir)
            candidate.replace(runtime)
        finally:
            if candidate.exists():
                shutil.rmtree(candidate, ignore_errors=True)
    _validate_runtime(runtime)
    _install_runtime_entrypoint(runtime, state_dir=state_dir)
    return relay_runtime_python(state_dir)


def activate_relay_runtime(state_dir: Path) -> None:
    """Atomically route the standing launch path to the verified runtime."""
    _activate_launch_link(state_dir)


def create_release_venv(path: Path, runtime_python: Path) -> None:
    """Create an isolated package environment using the stable Python version."""
    result = subprocess.run(
        [str(runtime_python), "-m", "venv", "--copies", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RelayReleaseError(
            RELAY_RELEASE_INSTALL_FAILED,
            "stable relay Python could not create the isolated release: "
            f"{subprocess_failure_detail(result)}",
        )


def subprocess_failure_detail(result: subprocess.CompletedProcess[str]) -> str:
    value = str(result.stderr or result.stdout or f"exit {result.returncode}").strip()
    return value[-1200:]


def _create_runtime(path: Path) -> None:
    venv.EnvBuilder(with_pip=False, symlinks=False).create(path)


def _preserve_active_release(state_dir: Path, release: Path) -> None:
    active = relay_active_release_path(state_dir)
    if active.exists() or active.is_symlink():
        return
    temporary = state_dir / f".{RELAY_ACTIVE_RELEASE_NAME}-{uuid.uuid4().hex}"
    try:
        temporary.symlink_to(release, target_is_directory=True)
        os.replace(temporary, active)
    finally:
        temporary.unlink(missing_ok=True)


def _activate_launch_link(state_dir: Path) -> None:
    if relay_launch_targets_runtime(state_dir):
        return
    launch = relay_launch_path(state_dir)
    temporary = state_dir / f".{RELAY_LAUNCH_LINK_NAME}-{uuid.uuid4().hex}"
    try:
        temporary.symlink_to(relay_runtime_path(state_dir), target_is_directory=True)
        os.replace(temporary, launch)
    finally:
        temporary.unlink(missing_ok=True)


def _validate_runtime(runtime: Path) -> None:
    python = runtime / "bin" / "python"
    try:
        owned = python.resolve(strict=True).is_relative_to(runtime.resolve(strict=True))
    except OSError:
        owned = False
    if (
        runtime.is_symlink()
        or not python.is_file()
        or not os.access(python, os.X_OK)
        or not owned
    ):
        raise RelayReleaseError(
            RELAY_RELEASE_INSTALL_FAILED,
            f"stable relay runtime is incomplete at {runtime}. Recovery: move "
            "that runtime directory aside, then retry the relay install.",
        )


def _install_runtime_entrypoint(runtime: Path, *, state_dir: Path) -> None:
    target = runtime / "bin" / "yoke"
    source = RUNTIME_ENTRYPOINT_SOURCE.read_text(encoding="utf-8")
    source = source.replace("__YOKE_ACTIVE_RELEASE__", RELAY_ACTIVE_RELEASE_NAME)
    body = source[source.index("\n") :]
    content = f"#!{relay_runtime_python(state_dir)} -I{body}"
    try:
        if target.read_text(encoding="utf-8") == content and os.access(target, os.X_OK):
            return
    except OSError:
        pass
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o755)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "VenvCreator",
    "activate_relay_runtime",
    "create_release_venv",
    "ensure_relay_runtime",
    "subprocess_failure_detail",
]
