"""Dependency detection and installation helpers for worktrees.

Extracted from worktree.py. Callers import these from worktree.py which
re-exports them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from yoke_core.domain import runtime_settings


DEPS_INSTALL_TIMEOUT_CONFIG = "worktree_dep_install_timeout_seconds"
DEFAULT_DEPS_INSTALL_TIMEOUT_SECONDS = 600


# ---------------------------------------------------------------------------
# Internal subprocess helper (local copy — avoids circular import with worktree.py)
# ---------------------------------------------------------------------------

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
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return subprocess.CompletedProcess(
            cmd, returncode=1, stdout="",
            stderr=f"{cmd[0] if cmd else '<empty>'}: {type(exc).__name__}: {exc}",
        )


# ---------------------------------------------------------------------------
# DepInstallSpec and detector tables
# ---------------------------------------------------------------------------

@dataclass
class DepInstallSpec:
    """Describes a dependency install action."""
    tool: str       # e.g., "npm", "pip", "yarn"
    command: List[str]  # full command
    cwd: str        # directory to run in
    label: str      # human-readable description


# Detection order: lockfile-first, then fallback
_ROOT_DETECTORS = [
    ("package-lock.json", "npm",   ["npm", "ci"],                           "npm ci"),
    ("yarn.lock",         "yarn",  ["yarn", "install", "--frozen-lockfile"], "yarn install --frozen-lockfile"),
    ("pnpm-lock.yaml",   "pnpm",  ["pnpm", "install", "--frozen-lockfile"],"pnpm install --frozen-lockfile"),
    ("package.json",      "npm",   ["npm", "install"],                      "npm install"),
]

_PYTHON_DETECTORS = [
    ("requirements.txt", "pip",    ["pip", "install", "-r", "requirements.txt"], "pip install -r requirements.txt"),
    ("Pipfile.lock",     "pipenv", ["pipenv", "install"],                        "pipenv install"),
]

_OTHER_DETECTORS = [
    ("Gemfile.lock", "bundle", ["bundle", "install"],   "bundle install"),
    ("go.sum",       "go",     ["go", "mod", "download"], "go mod download"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_playwright_cache(project_id: Optional[str], worktree_path: Optional[str]) -> Optional[str]:
    """Resolve the Playwright browser cache path.

    - With project ID: ``$HOME/.yoke/playwright-cache/{project}``
    - Without project but with worktree: ``{worktree}/.playwright-cache``
    - Neither: ``None``
    """
    if project_id:
        return os.path.join(os.path.expanduser("~"), ".yoke", "playwright-cache", project_id)
    if worktree_path:
        return os.path.join(worktree_path, ".playwright-cache")
    return None


def detect_deps(worktree_path: str) -> List[DepInstallSpec]:
    """Detect dependency files in *worktree_path* and return install specs.

    Returns an empty list if no dependency files are found.
    Handles root-level detection first, then nested fallback.
    """
    specs: List[DepInstallSpec] = []

    # --- Root-level Node.js ---
    node_found = False
    for filename, tool, cmd, label in _ROOT_DETECTORS:
        if os.path.isfile(os.path.join(worktree_path, filename)):
            specs.append(DepInstallSpec(
                tool=tool, command=cmd, cwd=worktree_path,
                label=f"Detected {filename} — running {label}",
            ))
            node_found = True
            break  # First match wins (lockfile priority)

    # --- Root-level Python ---
    python_found = False
    for filename, tool, cmd, label in _PYTHON_DETECTORS:
        if os.path.isfile(os.path.join(worktree_path, filename)):
            specs.append(DepInstallSpec(
                tool=tool, command=cmd, cwd=worktree_path,
                label=f"Detected {filename} — running {label}",
            ))
            python_found = True
            break

    # --- Root-level other (Ruby, Go) ---
    for filename, tool, cmd, label in _OTHER_DETECTORS:
        if os.path.isfile(os.path.join(worktree_path, filename)):
            specs.append(DepInstallSpec(
                tool=tool, command=cmd, cwd=worktree_path,
                label=f"Detected {filename} — running {label}",
            ))

    # --- Nested fallback ---
    if not node_found and not python_found and not specs:
        nested_spec = _detect_nested_deps(worktree_path)
        if nested_spec:
            specs.extend(nested_spec)

    return specs


def _detect_nested_deps(worktree_path: str) -> List[DepInstallSpec]:
    """Search up to 3 levels deep for dependency files.

    A nested lockfile carried by the repo does not by itself prove the
    installer is set up on this host. When the install tool is not on
    PATH, emit one informational line and skip — the prior behavior
    queued the install, hit FileNotFoundError, and surfaced N
    signal-less "non-fatal" warnings (one per worktree).
    """
    specs: List[DepInstallSpec] = []

    # Node.js nested detection (priority order)
    node_searches = [
        ("package-lock.json", ["npm", "ci"], "npm ci"),
        ("yarn.lock", ["yarn", "install", "--frozen-lockfile"], "yarn install --frozen-lockfile"),
        ("pnpm-lock.yaml", ["pnpm", "install", "--frozen-lockfile"], "pnpm install --frozen-lockfile"),
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
            specs.append(DepInstallSpec(
                tool=cmd[0], command=cmd, cwd=nested_dir,
                label=f"Detected nested {filename} at {rel} — running {label}",
            ))
            node_found = True
            break

    # Python nested detection
    if not node_found:
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
                specs.append(DepInstallSpec(
                    tool="pip",
                    command=["pip", "install", "-r", "requirements.txt"],
                    cwd=nested_dir,
                    label=f"Detected nested requirements.txt at {rel} — running pip install",
                ))

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
        # Skip the packaged Browser QA runtime sources: npm installs for
        # that tree run in the machine runtime dir
        # (~/.yoke/browser-runtime/), never inside a checkout.
        if rel == "runtime" and "browser_runtime" in dirnames:
            dirnames.remove("browser_runtime")
        if filename in filenames:
            return os.path.join(dirpath, filename)
    return None


def install_worktree_deps(
    worktree_path: str,
    project_id: Optional[str] = None,
    *,
    scripts_dir: Optional[str] = None,
) -> int:
    """Auto-install project dependencies in a worktree.

    Returns 0 on success, 1 on failure.
    """
    if not os.path.isdir(worktree_path):
        print(f"Error: worktree path does not exist: {worktree_path}", file=sys.stderr)
        return 1

    if scripts_dir is None:
        from yoke_core.api.repo_root import find_repo_root

        scripts_dir = str(
            find_repo_root(Path(__file__))
            / ".agents" / "skills" / "yoke" / "scripts"
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
            print(f"Installing deps via project setup_command: {setup_cmd}", file=sys.stderr)
            r = subprocess.run(
                setup_cmd, shell=True, cwd=worktree_path,
                capture_output=False, timeout=install_timeout,
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
    """Get the project's ``setup_command`` capability, if any.

    Routes through ``yoke_core.domain.projects.cmd_capability_get_settings`` in
    place of the retired ``project-db.sh`` shell shim. ``scripts_dir`` is
    retained in the signature for call-site compatibility but is unused.
    """
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
