"""Core helpers for the venv-independent ``yoke`` launcher installer."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from yoke_core.tools.install_yoke_launcher_cleanup import (
    YOKE_EDITABLE_PACKAGE_NAMES,
    cleanup_stale_editable_yoke_metadata,
)


TARGET_PRIORITY: Tuple[Tuple[str, str], ...] = (
    ("/opt/homebrew/bin", "homebrew_apple_silicon"),
    ("/usr/local/bin", "homebrew_intel_or_linux"),
    ("~/.local/bin", "fallback_user_local"),
)

MIN_PYTHON: Tuple[int, int] = (3, 9)
YOKE_PACKAGE_NAME = "yoke"
LAUNCHER_FILENAME = "yoke"
LAUNCHER_SOURCE = Path(__file__).resolve().parent / "yoke_launcher.py"
PROBE_BYTES = 4096
LAUNCHER_FINGERPRINT_IMPORT = "from yoke_cli.main"
LEGACY_LAUNCHER_FINGERPRINT_IMPORT = "from runtime.api.cli.yoke_operations_cli"
_LOCAL_WORKSPACE_PACKAGE_KEYS = frozenset(
    name.replace("_", "-").lower() for name in YOKE_EDITABLE_PACKAGE_NAMES
)


class InstallError(RuntimeError):
    """Raised when an install step refuses to proceed."""


@dataclass(frozen=True)
class TargetChoice:
    path: Path
    label: str


def verify_python_version(min_version: Tuple[int, int] = MIN_PYTHON) -> None:
    if sys.version_info[:2] < min_version:
        have = ".".join(str(x) for x in sys.version_info[:3])
        want = ".".join(str(x) for x in min_version)
        raise InstallError(f"python {want}+ required; running {have}.")


def _is_externally_managed() -> bool:
    marker = Path(sysconfig.get_path("stdlib")) / "EXTERNALLY-MANAGED"
    return marker.is_file()


def verify_repo_root(cwd: Path) -> Path:
    pyproject = cwd / "pyproject.toml"
    if not pyproject.is_file():
        raise InstallError(
            f"no pyproject.toml in {cwd}; run from the Yoke repo root."
        )
    text = pyproject.read_text(encoding="utf-8", errors="replace")
    needle = f'name = "{YOKE_PACKAGE_NAME}"'
    if needle not in text:
        raise InstallError(
            f"pyproject.toml does not declare the Yoke package ({needle!r})."
        )
    return cwd


def _dependency_package_key(dependency: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", dependency)
    if not match:
        return ""
    return match.group(1).replace("_", "-").lower()


def _runtime_dependency_strings(deps: Iterable[object]) -> List[str]:
    return [
        dep
        for dep in deps
        if isinstance(dep, str)
        and _dependency_package_key(dep) not in _LOCAL_WORKSPACE_PACKAGE_KEYS
    ]


def read_pyproject_deps(cwd: Path) -> List[str]:
    """Return the ``[project] dependencies`` array from ``cwd/pyproject.toml``."""
    pyproject = cwd / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    try:
        import tomllib

        data = tomllib.loads(text)
        deps = data.get("project", {}).get("dependencies", [])
        if isinstance(deps, list) and deps:
            return _runtime_dependency_strings(deps)
    except ImportError:
        pass
    match = re.search(
        r"^dependencies\s*=\s*\[(.*?)^\]",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise InstallError(
            f"pyproject.toml at {pyproject} has no top-level "
            f"[project] dependencies array."
        )
    deps = _runtime_dependency_strings(re.findall(r'"([^"]+)"', match.group(1)))
    if not deps:
        raise InstallError(
            f"pyproject.toml at {pyproject} has an empty "
            f"[project] dependencies array."
        )
    return deps


def run_pip_install_deps(
    cwd: Path,
    *,
    allow_system_packages: bool = True,
    stream=None,
) -> None:
    """Install Yoke's pinned runtime deps parsed from ``pyproject.toml``."""
    env = os.environ.copy()
    if _is_externally_managed() and env.get("PIP_BREAK_SYSTEM_PACKAGES") != "1":
        if allow_system_packages:
            env["PIP_BREAK_SYSTEM_PACKAGES"] = "1"
            out = stream if stream is not None else sys.stdout
            out.write(
                f"Detected externally-managed Python at {sys.executable};\n"
                f"setting PIP_BREAK_SYSTEM_PACKAGES=1 for this install.\n"
                f"(Pass --no-system-packages to opt out and use a venv instead.)\n\n"
            )
        else:
            raise InstallError(
                f"Python at {sys.executable} is externally-managed (PEP 668).\n"
                f"  Either: re-run without --no-system-packages, or\n"
                f"          create a venv: python3 -m venv .venv && source .venv/bin/activate"
            )
    run_pip_uninstall_old_yoke_packages(cwd, env=env, stream=stream)
    deps = read_pyproject_deps(cwd)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", *deps],
        cwd=str(cwd),
        env=env,
    )


def run_pip_uninstall_old_yoke_packages(
    cwd: Path,
    *,
    env: Optional[dict[str, str]] = None,
    stream=None,
) -> None:
    """Remove stale editable/package installs before launcher-based install."""
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "uninstall",
            "-y",
            *YOKE_EDITABLE_PACKAGE_NAMES,
        ],
        cwd=str(cwd),
        env=env or os.environ.copy(),
    )
    cleanup_stale_editable_yoke_metadata(stream=stream)


def _is_writable_no_sudo(directory: Path) -> bool:
    if directory.is_dir():
        return os.access(str(directory), os.W_OK)
    parent = directory.parent
    if parent.is_dir():
        return os.access(str(parent), os.W_OK)
    return False


def _path_entries(env_path: str) -> Iterable[str]:
    return (entry for entry in env_path.split(os.pathsep) if entry)


def _on_path(directory: Path, env_path: str) -> bool:
    expanded = str(directory.expanduser().resolve(strict=False))
    for entry in _path_entries(env_path):
        try:
            candidate = str(Path(entry).expanduser().resolve(strict=False))
        except OSError:
            continue
        if candidate == expanded:
            return True
    return False


def auto_detect_target(
    home: Path,
    override: Optional[str] = None,
    force_user: bool = False,
    force_system: bool = False,
    env_path: Optional[str] = None,
) -> TargetChoice:
    if override:
        return TargetChoice(Path(override).expanduser().resolve(strict=False), "override")
    if force_user:
        path, label = TARGET_PRIORITY[2]
        return TargetChoice(Path(path).expanduser().resolve(strict=False), label)
    if force_system:
        path, label = TARGET_PRIORITY[1]
        return TargetChoice(Path(path).expanduser().resolve(strict=False), label)
    env_path_str = env_path if env_path is not None else os.environ.get("PATH", "")
    for raw, label in TARGET_PRIORITY:
        directory = Path(raw).expanduser().resolve(strict=False)
        if _is_writable_no_sudo(directory) and _on_path(directory, env_path_str):
            return TargetChoice(directory, label)
    raw, label = TARGET_PRIORITY[2]
    return TargetChoice(Path(raw).expanduser().resolve(strict=False), label)


def refuse_foreign_binary(target_path: Path, force: bool = False) -> None:
    if not target_path.exists():
        return
    if force:
        return
    try:
        with target_path.open("rb") as fh:
            head = fh.read(PROBE_BYTES)
    except OSError as exc:
        raise InstallError(f"cannot probe {target_path}: {exc}") from exc
    try:
        text = head.decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - decode is lossy by default
        raise InstallError(f"cannot decode {target_path}: {exc}") from exc
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#!"):
        raise InstallError(
            f"{target_path} exists but is not a python script; pass --force to overwrite."
        )
    shebang = lines[0]
    if "python" not in shebang:
        raise InstallError(
            f"{target_path} shebang ({shebang!r}) is not a python interpreter; pass --force."
        )
    if (
        LAUNCHER_FINGERPRINT_IMPORT in text
        or LEGACY_LAUNCHER_FINGERPRINT_IMPORT in text
    ):
        return
    raise InstallError(
        f"{target_path} does not look like a Yoke launcher "
        f"(no {LAUNCHER_FINGERPRINT_IMPORT!r}); pass --force to overwrite."
    )


def write_launcher(
    target_path: Path,
    source: Optional[Path] = None,
    *,
    default_home: Optional[Path] = None,
) -> None:
    actual = source if source is not None else LAUNCHER_SOURCE
    target_path.parent.mkdir(parents=True, exist_ok=True)
    text = Path(actual).read_text(encoding="utf-8")
    if default_home is not None:
        text = text.replace(
            "DEFAULT_YOKE_HOME = None",
            f"DEFAULT_YOKE_HOME = {str(default_home)!r}",
        )
    pinned_shebang = f"#!{sys.executable}"
    if text.startswith("#!") and "\n" in text:
        first_newline = text.index("\n")
        text = pinned_shebang + text[first_newline:]
    else:
        text = pinned_shebang + "\n" + text
    target_path.write_text(text, encoding="utf-8")
    os.chmod(str(target_path), 0o755)


def verify_path_includes(
    target_dir: Path,
    env_path: Optional[str] = None,
    stream=None,
) -> bool:
    env_path_str = env_path if env_path is not None else os.environ.get("PATH", "")
    if _on_path(target_dir, env_path_str):
        return True
    out = stream if stream is not None else sys.stderr
    snippet_dir = str(target_dir)
    out.write(
        f"WARNING: {snippet_dir} is not on PATH.\n"
        f"  Add to ~/.bashrc:  export PATH=\"{snippet_dir}:$PATH\"\n"
        f"  Add to ~/.zshrc:   export PATH=\"{snippet_dir}:$PATH\"\n"
    )
    return False


def run_verification(
    launcher: str = "yoke",
    *,
    verify_env: Optional[str] = None,
    stream=None,
) -> None:
    env = os.environ.copy()
    out = stream if stream is not None else sys.stdout
    if verify_env:
        env["YOKE_ENV"] = verify_env
        out.write(f"Verifying yoke launcher with YOKE_ENV={verify_env}\n")
    subprocess.check_call([launcher, "--version"], env=env)
    subprocess.check_call([launcher, "status"], env=env)
