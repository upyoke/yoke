"""Shared runtime helpers for the merge-worktree engine."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from yoke_core.domain import runtime_settings

_GIT_TIMEOUT_ENV = "YOKE_GIT_COMMAND_TIMEOUT_SECONDS"
_DEFAULT_GIT_COMMAND_TIMEOUT_SECONDS = 120
_GIT_TIMEOUT_EXIT_CODE = 124


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw

def _repo_root() -> Path:
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


def _db_path() -> str:
    """Return the retired DB path token for legacy call signatures."""
    return ""


def _connect():
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _git_command_timeout_seconds() -> int:
    """Return the timeout to use for git subprocesses."""
    raw = os.environ.get(_GIT_TIMEOUT_ENV)
    if raw:
        try:
            parsed = int(raw)
            if parsed > 0:
                return parsed
        except ValueError:
            pass

    return runtime_settings.get_seconds(
        "git_command_timeout",
        _DEFAULT_GIT_COMMAND_TIMEOUT_SECONDS,
    )


def _git_env() -> dict[str, str]:
    """Return a git-safe environment that never blocks on interactive prompts."""
    env = os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GCM_INTERACTIVE", "Never")
    env.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes")
    return env


def _source_pythonpath(existing: str = "") -> str:
    root = _repo_root()
    entries = [
        root,
        root / "packages" / "yoke-core" / "src",
        root / "packages" / "yoke-contracts" / "src",
        root / "packages" / "yoke-cli" / "src",
        root / "packages" / "yoke-harness" / "src",
    ]
    seen: set[str] = set()
    result: list[str] = []
    for entry in [str(path) for path in entries] + existing.split(os.pathsep):
        if entry and entry not in seen:
            seen.add(entry)
            result.append(entry)
    return os.pathsep.join(result)


def _git_timeout_result(
    cmd: list[str],
    timeout_seconds: int,
    exc: subprocess.TimeoutExpired,
) -> subprocess.CompletedProcess[str]:
    """Convert a timed out git subprocess into a non-raising failure result."""
    stdout = exc.output or ""
    stderr = exc.stderr or ""
    detail = (
        f"git command timed out after {timeout_seconds}s: "
        f"{' '.join(cmd)}"
    )
    stderr = f"{stderr.rstrip()}\n{detail}\n" if stderr else f"{detail}\n"
    return subprocess.CompletedProcess(
        cmd,
        _GIT_TIMEOUT_EXIT_CODE,
        stdout,
        stderr,
    )


def _run_git(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    capture: bool = False,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a git command."""
    cmd = ["git"] + args
    timeout_seconds = _git_command_timeout_seconds()
    kwargs: dict[str, Any] = {
        "text": True,
        "check": check,
        "env": _git_env(),
        "timeout": timeout_seconds,
    }
    if cwd:
        kwargs["cwd"] = str(cwd)
    if capture:
        kwargs["capture_output"] = True
    else:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    try:
        return subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired as exc:
        result = _git_timeout_result(cmd, timeout_seconds, exc)
        if check:
            raise subprocess.CalledProcessError(
                result.returncode,
                cmd,
                output=result.stdout,
                stderr=result.stderr,
            ) from exc
        return result


def _run_python_module(
    module: str,
    args: list[str],
    *,
    env_overrides: dict[str, str] | None = None,
    capture: bool = False,
    cwd: str | Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a Yoke Python domain/CLI module as a subprocess.

    Invokes ``python3 -m <module>`` for the few remaining in-merge
    call sites that still need a child-process boundary.
    """
    env = os.environ.copy()
    env.pop("YOKE_DB", None)
    if env_overrides:
        env.update(env_overrides)
    env["PYTHONPATH"] = _source_pythonpath(env.get("PYTHONPATH", ""))
    cmd = [sys.executable, "-m", module, *args]
    kwargs: dict[str, Any] = {"env": env, "text": True, "check": False}
    if capture:
        kwargs["capture_output"] = True
    if cwd:
        kwargs["cwd"] = str(cwd)
    return subprocess.run(cmd, **kwargs)


def _print(msg: str, *, err: bool = False) -> None:
    print(msg, file=sys.stderr if err else sys.stdout, flush=True)


def _already_merged_message(branch: str, target: str, repo_root: str) -> str:
    """Distinguish no-code branches from branches that are already merged."""
    unique = _run_git(
        ["rev-list", f"{target}..{branch}", "--count"],
        cwd=repo_root, capture=True,
    )
    if unique.returncode == 0 and unique.stdout.strip() == "0":
        return (
            f"Branch '{branch}' has no commits diverging from {target} "
            f"\u2014 nothing to merge (no-code item)."
        )
    return f"Branch '{branch}' is already merged to {target} \u2014 nothing to merge."
