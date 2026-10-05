"""Dependency detection and installation helpers exported by worktree.py."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from yoke_contracts.playwright_cache import resolve_playwright_cache
from yoke_core.domain import runtime_settings
from yoke_core.domain.worktree_python_dependency_owner import (
    uv_provisioned_projects,
    uv_provisioned_skip_note,
)


DEPS_INSTALL_TIMEOUT_CONFIG = "worktree_dep_install_timeout_seconds"
DEFAULT_DEPS_INSTALL_TIMEOUT_SECONDS = 600


def _run(
    cmd: List[str],
    cwd: Optional[str] = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Run a subprocess with timeout, capturing output.

    On TimeoutExpired / FileNotFoundError / OSError, record the exception
    class + message into ``stderr`` of the returned CompletedProcess so the
    failure signal survives — the prior swallow-to-empty-stderr behavior
    turned "npm not installed" into a content-free non-fatal warning.
    """
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return subprocess.CompletedProcess(
            cmd,
            returncode=1,
            stdout="",
            stderr=f"{cmd[0] if cmd else '<empty>'}: {type(exc).__name__}: {exc}",
        )


@dataclass
class DepInstallSpec:
    """Describes a dependency install action."""

    tool: str  # e.g., "npm", "pip", "yarn"
    command: List[str]  # full command
    cwd: str  # directory to run in
    label: str  # human-readable description


# Detection order: lockfile-first, then fallback
_ROOT_DETECTORS = [
    ("package-lock.json", "npm", ["npm", "ci"], "npm ci"),
    (
        "yarn.lock",
        "yarn",
        ["yarn", "install", "--frozen-lockfile"],
        "yarn install --frozen-lockfile",
    ),
    (
        "pnpm-lock.yaml",
        "pnpm",
        ["pnpm", "install", "--frozen-lockfile"],
        "pnpm install --frozen-lockfile",
    ),
    ("package.json", "npm", ["npm", "install"], "npm install"),
]

# Convention detectors for a lane whose Python dependencies nothing else
# owns. A uv-managed lane is NOT one of those: see `uv_provisioned_projects`.
_PYTHON_DETECTORS = [
    (
        "requirements.txt",
        "pip",
        ["pip", "install", "-r", "requirements.txt"],
        "pip install -r requirements.txt",
    ),
    ("Pipfile.lock", "pipenv", ["pipenv", "install"], "pipenv install"),
]

_OTHER_DETECTORS = [
    ("Gemfile.lock", "bundle", ["bundle", "install"], "bundle install"),
    ("go.sum", "go", ["go", "mod", "download"], "go mod download"),
]


def detect_deps(worktree_path: str) -> List[DepInstallSpec]:
    """Return root-first install specs, or an empty list when none are found."""
    specs: List[DepInstallSpec] = []

    # --- Root-level Node.js ---
    node_found = False
    for filename, tool, cmd, label in _ROOT_DETECTORS:
        if os.path.isfile(os.path.join(worktree_path, filename)):
            specs.append(
                DepInstallSpec(
                    tool=tool,
                    command=cmd,
                    cwd=worktree_path,
                    label=f"Detected {filename} — running {label}",
                )
            )
            node_found = True
            break  # First match wins (lockfile priority)

    # --- Python: uv-managed projects first, conventions only otherwise ---
    uv_projects = uv_provisioned_projects(worktree_path)
    python_found = bool(uv_projects)
    if uv_projects:
        for label in uv_projects:
            print(uv_provisioned_skip_note(label), file=sys.stderr)
    else:
        for filename, tool, cmd, label in _PYTHON_DETECTORS:
            if os.path.isfile(os.path.join(worktree_path, filename)):
                specs.append(
                    DepInstallSpec(
                        tool=tool,
                        command=cmd,
                        cwd=worktree_path,
                        label=f"Detected {filename} — running {label}",
                    )
                )
                python_found = True
                break

    # --- Root-level other (Ruby, Go) ---
    for filename, tool, cmd, label in _OTHER_DETECTORS:
        if os.path.isfile(os.path.join(worktree_path, filename)):
            specs.append(
                DepInstallSpec(
                    tool=tool,
                    command=cmd,
                    cwd=worktree_path,
                    label=f"Detected {filename} — running {label}",
                )
            )

    # --- Nested fallback ---
    # A uv-managed lane keeps its Python axis owned while still allowing a
    # nested Node app to be detected: the two are independent.
    if not node_found and not specs:
        nested_spec = _detect_nested_deps(worktree_path, skip_python=python_found)
        if nested_spec:
            specs.extend(nested_spec)

    return specs


def _detect_nested_deps(
    worktree_path: str,
    *,
    skip_python: bool = False,
) -> List[DepInstallSpec]:
    """Search three levels deep, skipping installers absent from PATH.

    A lockfile alone does not prove its installer is available. Skip with
    an informational line rather than a content-free install failure.
    ``skip_python`` preserves a lane environment owned by another installer.
    """
    specs: List[DepInstallSpec] = []

    # Node.js nested detection (priority order)
    node_searches = [
        ("package-lock.json", ["npm", "ci"], "npm ci"),
        (
            "yarn.lock",
            ["yarn", "install", "--frozen-lockfile"],
            "yarn install --frozen-lockfile",
        ),
        (
            "pnpm-lock.yaml",
            ["pnpm", "install", "--frozen-lockfile"],
            "pnpm install --frozen-lockfile",
        ),
        ("package.json", ["npm", "install"], "npm install"),
    ]

    node_found = False
    for filename, cmd, label in node_searches:
        found_path = _find_nested(worktree_path, filename, max_depth=3)
        if found_path:
            nested_dir = os.path.dirname(found_path)
            rel = os.path.relpath(nested_dir, worktree_path)
            if shutil.which(cmd[0]) is None:
                print(
                    f"Skipping nested {filename} at {rel}: {cmd[0]} not on PATH",
                    file=sys.stderr,
                )
                node_found = True  # don't fall through to other Node candidates
                break
            specs.append(
                DepInstallSpec(
                    tool=cmd[0],
                    command=cmd,
                    cwd=nested_dir,
                    label=f"Detected nested {filename} at {rel} — running {label}",
                )
            )
            node_found = True
            break

    # Python nested detection
    if not node_found and not skip_python:
        found_req = _find_nested(worktree_path, "requirements.txt", max_depth=3)
        if found_req:
            nested_dir = os.path.dirname(found_req)
            rel = os.path.relpath(nested_dir, worktree_path)
            if shutil.which("pip") is None:
                print(
                    f"Skipping nested requirements.txt at {rel}: pip not on PATH",
                    file=sys.stderr,
                )
            else:
                specs.append(
                    DepInstallSpec(
                        tool="pip",
                        command=["pip", "install", "-r", "requirements.txt"],
                        cwd=nested_dir,
                        label=f"Detected nested requirements.txt at {rel} — running pip install",
                    )
                )

    return specs


def _find_nested(root: str, filename: str, max_depth: int = 3) -> Optional[str]:
    """Walk *root* up to *max_depth* levels looking for *filename*."""
    for dirpath, dirnames, filenames in os.walk(root):
        # Compute depth
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > max_depth:
            dirnames.clear()
            continue
        # Skip node_modules
        if "node_modules" in dirnames:
            dirnames.remove("node_modules")
        if filename in filenames:
            return os.path.join(dirpath, filename)
    return None


def install_worktree_deps(
    worktree_path: str,
    project_id: Optional[str] = None,
    *,
    scripts_dir: Optional[str] = None,
) -> int:
    """Install project dependencies; return 0 on success, 1 on failure."""
    if not os.path.isdir(worktree_path):
        print(f"Error: worktree path does not exist: {worktree_path}", file=sys.stderr)
        return 1

    if scripts_dir is None:
        from yoke_core.api.repo_root import find_repo_root

        scripts_dir = str(
            find_repo_root(Path(__file__)) / ".agents" / "skills" / "yoke" / "scripts"
        )

    # --- Playwright cache isolation ---
    pw_cache = resolve_playwright_cache(project_id, worktree_path)
    if pw_cache:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = pw_cache
        print(f"Playwright cache: {pw_cache}", file=sys.stderr)

    install_timeout = runtime_settings.get_seconds(
        DEPS_INSTALL_TIMEOUT_CONFIG,
        DEFAULT_DEPS_INSTALL_TIMEOUT_SECONDS,
    )

    # --- Project capability override ---
    if project_id:
        setup_cmd = _get_setup_command(project_id, scripts_dir)
        if setup_cmd:
            print(
                f"Installing deps via project setup_command: {setup_cmd}",
                file=sys.stderr,
            )
            r = subprocess.run(
                setup_cmd,
                shell=True,
                cwd=worktree_path,
                capture_output=False,
                timeout=install_timeout,
            )
            return r.returncode

    # --- Convention-based detection ---
    specs = detect_deps(worktree_path)

    if not specs:
        print("No dependency files detected — skipping install", file=sys.stderr)
        return 0

    exit_code = 0
    for spec in specs:
        print(spec.label, file=sys.stderr)
        r = _run(spec.command, cwd=spec.cwd, timeout=install_timeout)
        if r.returncode != 0:
            exit_code = 1
            if r.stderr:
                print(r.stderr.rstrip(), file=sys.stderr)

    return exit_code


def _get_setup_command(project_id: str, scripts_dir: str) -> Optional[str]:
    """Read the setup_command capability; scripts_dir is an unused caller argument."""
    from yoke_core.domain import projects

    try:
        raw = projects.cmd_capability_get_settings(project_id, "setup_command")
    except Exception:
        return None
    if not raw or raw.strip() in ("", "{}"):
        return None
    # Extract command from JSON: {"command": "..."}
    import json

    try:
        data = json.loads(raw.strip())
        return data.get("command")
    except (json.JSONDecodeError, AttributeError):
        return None
