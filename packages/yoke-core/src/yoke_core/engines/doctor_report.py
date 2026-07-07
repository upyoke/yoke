"""Report generation, shared types, and utility helpers for doctor sub-modules.

Provides CheckResult, RecordCollector (report formatting), DoctorArgs, and
small helper functions used across multiple HC sub-modules.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from yoke_core.domain import runtime_settings
from yoke_core.domain.schema_common import (
    _column_exists as _schema_column_exists,
    _table_exists as _schema_table_exists,
)


@dataclass
class CheckResult:
    """One recorded result from a health check."""

    check_id: str
    check_name: str
    result: str  # PASS, WARN, FAIL
    detail: str


@dataclass
class DoctorArgs:
    """Parsed CLI arguments."""

    file: Optional[str] = None
    fix: bool = False
    only: Optional[str] = None
    quick: bool = False
    project: str = "yoke"
    db_path: Optional[str] = None  # for testing



class RecordCollector:
    """Collects health check results and produces Markdown output."""

    def __init__(self) -> None:
        self.results: List[CheckResult] = []

    def record(self, check_id: str, check_name: str, result: str, detail: str) -> None:
        self.results.append(CheckResult(check_id, check_name, result, detail))

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.result == "PASS")

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.results if r.result == "WARN")

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.result == "FAIL")

    @property
    def total_count(self) -> int:
        return len(self.results)

    def format_report(self) -> str:
        """Produce Markdown report matching shell doctor.sh output format."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        lines: List[str] = []
        lines.append("# Ouroboros Health Report")
        lines.append(f"Generated: {timestamp}")
        lines.append("")
        lines.append("## Summary")
        lines.append(
            f"{self.total_count} checks run: {self.pass_count} passed, "
            f"{self.warn_count} warnings, {self.fail_count} failures"
        )
        lines.append("")

        # Failures section
        failures = [r for r in self.results if r.result == "FAIL"]
        if failures:
            lines.append("## Failures")
            for r in failures:
                lines.append(f"### {r.check_id}: {r.check_name}")
                lines.append(r.detail)
                lines.append("")

        # Warnings section
        warnings = [r for r in self.results if r.result == "WARN"]
        if warnings:
            lines.append("## Warnings")
            for r in warnings:
                lines.append(f"### {r.check_id}: {r.check_name}")
                lines.append(r.detail)
                lines.append("")

        # Passed section
        passed = [r for r in self.results if r.result == "PASS"]
        if passed:
            lines.append("## Passed")
            for r in passed:
                if r.detail:
                    lines.append(f"{r.check_id}: {r.check_name} \u2014 {r.detail}")
                else:
                    lines.append(f"{r.check_id}: {r.check_name}")

        return "\n".join(lines)


# GitHub-dependent HC slugs (skipped in --quick mode)
_GH_HCS = frozenset({
    "orphaned-gh-issues", "gh-orphan-detection", "missing-gh-issues",
    "title-drift", "body-drift", "reverse-completeness", "comment-sync",
    "label-drift", "state-drift", "frozen-label-drift", "blocked-label-drift", "stale-remote-branches",
    "wrong-repo-issues", "task-label-drift", "delegated-sync",
    "project-health", "project-gh-secrets", "project-vps-reachable",
    "branch-protection-required-check",
})

# Slugs for delegated sync HCs (dispatched to resync engine)
_DELEGATED_SYNC_HCS = [
    "missing-gh-issues", "orphan-epic-tasks", "title-drift", "body-drift",
    "reverse-completeness", "comment-sync", "label-drift", "state-drift",
    "frozen-label-drift", "blocked-label-drift", "task-label-drift",
]




def _should_run_hc(slug: str, args: DoctorArgs) -> bool:
    """Return True if the HC with *slug* should run given *args*."""
    if args.quick and slug in _GH_HCS:
        return False
    if args.only:
        allowed: set = set()
        alias_map = {
            "confabulation": "path-confabulation",
            "path-confabulation": "path-confabulation",
        }
        for raw in args.only.split(","):
            token = raw.strip()
            if not token:
                continue
            allowed.add(token)
            bare = token[3:] if token.startswith("HC-") else token
            allowed.add(bare)
            mapped = alias_map.get(bare)
            if mapped:
                allowed.add(mapped)
        if slug in allowed:
            return True
        # delegated-sync runs if any of its sub-HCs are requested
        if slug == "delegated-sync":
            return bool(allowed & set(_DELEGATED_SYNC_HCS))
        return False
    # Skip project-scoped HCs when running against yoke
    if slug.startswith("project-") and args.project == "yoke":
        return False
    return True


def _table_exists(conn, table_name: str) -> bool:
    """Return True if *table_name* exists in the database."""
    return _schema_table_exists(conn, table_name)



def _column_exists(conn, table_name: str, column_name: str) -> bool:
    """Return True if *column_name* exists on *table_name*."""
    return _schema_column_exists(conn, table_name, column_name)



def _now_epoch() -> int:
    return int(datetime.now(timezone.utc).timestamp())



def _iso_to_epoch(ts: str) -> int:
    """Parse an ISO timestamp to Unix epoch. Return 0 on failure."""
    if not ts:
        return 0
    ts = ts.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            dt = datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    return 0



def _run(
    cmd: List[str],
    cwd: Optional[str] = None,
    timeout: int = 30,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess, returning CompletedProcess. Never raises on non-zero exit."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        detail = f"timeout after {timeout}s"
        if stderr:
            detail = f"{detail}: {stderr.strip()}"
        return subprocess.CompletedProcess(cmd, returncode=124, stdout=stdout, stderr=detail)
    except (FileNotFoundError, OSError) as exc:
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr=str(exc))



def _resolve_repo_root() -> Optional[str]:
    """Return the repo root (git rev-parse --show-toplevel) or None."""
    r = _run(["git", "rev-parse", "--show-toplevel"])
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return None


def _read_config_value(key: str) -> Optional[str]:
    """Return the raw machine-config setting value, or None if absent."""
    raw = runtime_settings.get_str(key, "")
    return raw if raw.strip() else None


def _read_int_cutoff(key: str) -> Optional[int]:
    """Return the integer cutoff stored in machine config, or None."""
    raw = _read_config_value(key)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _read_str_cutoff(key: str) -> Optional[str]:
    """Return the string cutoff stored in machine config, or None."""
    raw = _read_config_value(key)
    if raw is None or not raw.strip():
        return None
    return raw.strip()



def _resolve_main_root() -> Optional[str]:
    """Resolve the main repo root, handling worktrees."""
    repo_root = _resolve_repo_root()
    if not repo_root:
        return None
    # Check if we're in a worktree
    git_dir = Path(repo_root) / ".git"
    if git_dir.is_file():
        # Worktree: .git is a file pointing to the main repo's .git dir
        content = git_dir.read_text().strip()
        if content.startswith("gitdir:"):
            git_path = content.split(":", 1)[1].strip()
            # e.g. /path/to/repo/.git/worktrees/YOK-N
            # The main repo is 3 levels up from there
            main_git = Path(git_path)
            if "worktrees" in main_git.parts:
                idx = main_git.parts.index("worktrees")
                main_root = Path(*main_git.parts[:idx - 1]) if idx >= 2 else None
                if main_root and main_root.exists():
                    return str(main_root)
    return repo_root
