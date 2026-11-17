"""Resolve parsed Bash operands on the machine that executes them.

Call after shell tokenization: backslashes in shell text are escapes, not
Windows separators. Git for Windows' cygpath owns its POSIX mount table;
a control-plane process must use client observations instead of its mounts.
"""

from __future__ import annotations

import ntpath
import posixpath
import os
import re
import shutil
import subprocess
from functools import lru_cache, wraps
from contextvars import ContextVar
from contextlib import contextmanager
from collections.abc import Mapping
from pathlib import Path

_CLIENT_PATHS: ContextVar[Mapping | None] = ContextVar(
    "bash_client_paths", default=None
)


@contextmanager
def client_path_scope(paths):
    """Bind one executing client's observations for a complete guard call."""
    token = _CLIENT_PATHS.set(paths)
    try:
        yield
    finally:
        _CLIENT_PATHS.reset(token)


def client_path_facts():
    """The current executing-client observations, absent outside a hook scope."""
    return _CLIENT_PATHS.get()


class BashPathResolutionError(ValueError):
    """The executing client cannot prove a Bash path's native destination."""


def with_client_paths(function=None, *, refuse=None):
    """Scope native resolution to the facts of one hook payload, including errors."""

    if function is None:
        return lambda target: with_client_paths(target, refuse=refuse)

    @wraps(function)
    def wrapped(payload, *args, **kwargs):
        from yoke_contracts.hook_runner.client_facts import (
            read_client_fact,
            WRITE_TARGETS_KEY,
        )

        fact = read_client_fact(payload, WRITE_TARGETS_KEY)
        paths = fact.get("bash_paths") if isinstance(fact, Mapping) else None
        token = _CLIENT_PATHS.set(
            paths if isinstance(paths, Mapping) else _CLIENT_PATHS.get()
        )
        try:
            if isinstance(fact, Mapping) and fact.get("path_resolution_error"):
                raise BashPathResolutionError(str(fact["path_resolution_error"]))
            return function(payload, *args, **kwargs)
        except BashPathResolutionError as exc:
            if refuse is None:
                raise
            return refuse(str(exc))
        finally:
            _CLIENT_PATHS.reset(token)

    return wrapped


_DRIVE = re.compile(r"^[A-Za-z]:[/\\]")


def windows_path(path: str) -> bool:
    return bool(_DRIVE.match(path)) or path.startswith("\\\\")


def is_absolute(path: str) -> bool:
    return path.startswith("/") or windows_path(path)


def canonical_native_path(path: str) -> str:
    """Canonicalize filesystem aliases locally; never probe foreign drives."""
    facts = _CLIENT_PATHS.get()
    if facts is not None:
        windows = bool(facts.get("windows"))
        text = path.replace("\\", "/") if windows else path
        aliases = facts.get("canonical", {})
        comparable = text.casefold() if windows else text
        for raw in sorted(aliases, key=len, reverse=True):
            prefix = raw.casefold() if windows else raw
            if comparable == prefix or comparable.startswith(prefix.rstrip("/") + "/"):
                text = aliases[raw] + text[len(raw) :]
                break
        return ntpath.normpath(text) if windows else posixpath.normpath(text)
    if windows_path(path) and os.name != "nt":
        return ntpath.normpath(path).replace("\\", "/")
    return os.path.realpath(path)


def is_under(path: str, root: str) -> bool:
    """Compare canonical paths using the executing client's separators and case."""
    if not path or not root:
        return False
    target, base = canonical_native_path(path), canonical_native_path(root)
    if windows_path(target) or windows_path(base):
        target, base = (
            target.replace("\\", "/").casefold(),
            base.replace("\\", "/").casefold(),
        )
    return target == base or target.startswith(base.rstrip("/") + "/")


@lru_cache(maxsize=1)
def git_cygpath() -> str:
    """Find cygpath beside Git for Windows, never Windows' WSL bash."""
    git = shutil.which("git")
    roots = []
    if git:
        executable = Path(git).resolve()
        roots.extend((executable.parent.parent, executable.parent.parent.parent))
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = os.environ.get(variable)
        if value:
            roots.append(
                Path(value) / ("Programs/Git" if variable == "LOCALAPPDATA" else "Git")
            )
    for root in roots:
        candidate = root / "usr/bin/cygpath.exe"
        if candidate.is_file() and (root / "cmd/git.exe").is_file():
            return str(candidate)
    raise BashPathResolutionError(
        "git_bash_unavailable: Git for Windows' cygpath.exe was not found; "
        "install Git for Windows, put its git.exe on PATH, and retry the command."
    )


@lru_cache(maxsize=1024)
def _mount_path(path: str) -> str:
    try:
        result = subprocess.run(
            [git_cygpath(), "-w", "--", path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BashPathResolutionError(
            "git_bash_path_resolution_failed: Git for Windows could not resolve "
            f"{path!r}; check its cygpath.exe installation and retry."
        ) from exc
    converted = result.stdout.strip()
    if not windows_path(converted):
        raise BashPathResolutionError(
            f"git_bash_path_resolution_failed: cygpath returned no native path for {path!r}; "
            "repair Git for Windows and retry."
        )
    return converted


def expand_home(path: str, *, home: str | None = None) -> str:
    facts = _CLIENT_PATHS.get()
    if home is None:
        home = (
            str(facts.get("home") or "")
            if facts is not None
            else os.path.expanduser("~")
        )
    if not home:
        return path
    if path == "~":
        return home
    if path.startswith("~/"):
        return join_path(home, path[2:])
    return path


def join_path(base: str, path: str) -> str:
    """Join parsed paths without applying the authority's drive semantics."""
    if is_absolute(path):
        return path
    if windows_path(base):
        joined = ntpath.join(base, path)
        return (
            joined
            if os.name == "nt" or (_CLIENT_PATHS.get() or {}).get("windows")
            else joined.replace("\\", "/")
        )
    return posixpath.join(base, path)


def resolve_bash_path(
    path: str, cwd: str = "", *, home: str | None = None, canonical: bool = True
) -> str:
    expanded = expand_home(path, home=home)
    if expanded.startswith("~"):
        return expanded
    facts = _CLIENT_PATHS.get()
    windows = (
        bool(facts.get("windows"))
        if facts is not None
        else os.name == "nt" or windows_path(cwd) or windows_path(expanded)
    )
    if windows and expanded.startswith("/") and not expanded.startswith("//"):
        mounts = facts.get("mount_paths", {}) if facts else {}
        observed = mounts.get(expanded)
        if observed is None:
            for raw in sorted(mounts, key=len, reverse=True):
                if expanded.startswith(raw.rstrip("/") + "/"):
                    observed = join_path(mounts[raw], expanded[len(raw) :].lstrip("/"))
                    break
        if isinstance(observed, str):
            return canonical_native_path(observed) if canonical else observed
        if facts or os.name != "nt":
            raise BashPathResolutionError(
                "git_bash_client_path_required: the Windows client's mount resolution "
                "is missing; refresh the client installation and retry the command."
            )
        expanded = _mount_path(expanded)
    if not is_absolute(expanded):
        if not cwd and facts is not None:
            raise BashPathResolutionError(
                "git_bash_client_cwd_required: the executing client did not supply a directory; "
                "set an explicit tool workdir and retry."
            )
        base = (
            resolve_bash_path(cwd, home=home)
            if windows and cwd.startswith("/")
            else cwd
        )
        expanded = join_path(base or os.getcwd(), expanded)
    if not canonical:
        return ntpath.normpath(expanded) if windows else posixpath.normpath(expanded)
    return canonical_native_path(expanded)
