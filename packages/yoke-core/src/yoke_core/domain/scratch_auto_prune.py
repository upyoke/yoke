"""Fail-closed cleanup for helper-owned machine scratch trees."""

from __future__ import annotations

import errno
import fcntl
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from yoke_core.domain import project_scratch_dir
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.schema_common import _column_exists, _table_exists


ORPHAN_AGE_THRESHOLDS_S: dict[str, int] = {
    "watcher-captures": 300,
    "payloads": 300,
    "scratch-dirs": 300,
    "hook-markers": 600,
    "harness-runtime-cache": 600,
    "dispatch-inputs": 600,
}
# ``storage`` is intentionally durable and must never be pruned as one generic
# bucket.  Only helper-owned storage kinds with an explicit lifecycle belong
# here.  Core image build directories are disposable assembly workspaces; new
# builds remove themselves in ``finally`` and this sweeps residue left by an
# interrupted or older builder after its owning session/process is proven dead.
ORPHAN_STORAGE_AGE_THRESHOLDS_S: dict[str, int] = {
    "core-image-build": 600,
}
AUTO_PRUNE_INTERVAL_S = 600
_PID_RUN = re.compile(r"^pid-(\d+)$")


@dataclass
class ScratchPruneResult:
    """One scratch scan/prune outcome."""

    issues: list[str] = field(default_factory=list)
    stale_count: int = 0
    removed_count: int = 0
    failure_count: int = 0
    protected_run_count: int = 0
    skipped_throttle: bool = False
    registry_error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "stale_count": self.stale_count,
            "removed_count": self.removed_count,
            "failure_count": self.failure_count,
            "protected_run_count": self.protected_run_count,
            "skipped_throttle": self.skipped_throttle,
            "registry_error": self.registry_error,
        }


def _session_states(conn: Any) -> tuple[set[str], set[str], str]:
    if not (
        _table_exists(conn, "harness_sessions")
        and _column_exists(conn, "harness_sessions", "session_id")
        and _column_exists(conn, "harness_sessions", "ended_at")
    ):
        return set(), set(), "harness_sessions liveness registry is unavailable"
    try:
        rows = query_rows(conn, "SELECT session_id, ended_at FROM harness_sessions")
    except Exception as exc:  # noqa: BLE001 - fail closed across DB boundaries
        return set(), set(), f"active session lookup failed: {exc}"
    active: set[str] = set()
    ended: set[str] = set()
    for row in rows:
        session_id = str(row["session_id"])
        (active if row["ended_at"] is None else ended).add(session_id)
    return active, ended, ""


def _pid_for_run(run_dir: Path) -> int | None:
    match = _PID_RUN.fullmatch(run_dir.name)
    return int(match.group(1)) if match else None


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _plain_run_dirs(global_root: Path) -> list[Path]:
    runs: list[Path] = []
    for run_dir in global_root.glob("*/sessions/*/runs/*"):
        session_dir = run_dir.parent.parent
        project_dir = session_dir.parent.parent
        if not run_dir.is_dir():
            continue
        if any(
            path.is_symlink()
            for path in (project_dir, session_dir.parent, session_dir, run_dir)
        ):
            continue
        runs.append(run_dir)
    return sorted(runs)


def _remove_empty_scaffold(run_dir: Path, result: ScratchPruneResult) -> None:
    session_dir = run_dir.parent.parent
    candidates = [
        *(run_dir / kind for kind in ORPHAN_AGE_THRESHOLDS_S),
        *(
            run_dir / "storage" / kind
            for kind in ORPHAN_STORAGE_AGE_THRESHOLDS_S
        ),
        run_dir / "storage",
        run_dir,
        run_dir.parent,
        session_dir,
        session_dir.parent,
        session_dir.parent.parent,
    ]
    for path in candidates:
        try:
            path.rmdir()
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.ENOTEMPTY, errno.EEXIST):
                result.failure_count += 1
                result.issues.append(
                    f"- empty-directory cleanup failed for {path}: {exc}"
                )


def _cleanup_entries(kind: str, sub_dir: Path) -> list[Path]:
    """Return lifecycle-owned entries at the granularity safe to delete."""
    if kind == "storage/core-image-build":
        # Shape: core-image-build/<environment>/<image-tag>.  Removing the
        # environment directory wholesale could race a fresh sibling tag.
        return sorted(
            tag_dir
            for environment_dir in sub_dir.iterdir()
            if environment_dir.is_dir() and not environment_dir.is_symlink()
            for tag_dir in environment_dir.iterdir()
            if tag_dir.is_dir() and not tag_dir.is_symlink()
        )
    return sorted(sub_dir.iterdir())


def _remove_empty_owned_parents(entry: Path, sub_dir: Path) -> None:
    parent = entry.parent
    while parent != sub_dir and parent.is_relative_to(sub_dir):
        try:
            parent.rmdir()
        except OSError as exc:
            if exc.errno in (errno.ENOENT, errno.ENOTEMPTY, errno.EEXIST):
                return
            raise
        parent = parent.parent


def prune_stale_scratch(
    conn: Any,
    *,
    fix: bool,
    now_epoch: int | None = None,
) -> ScratchPruneResult:
    """Scan or prune stale scratch with positive session/process proof.

    Known harness sessions are eligible only after ``ended_at`` is set.
    ``session-unknown`` runs are eligible only when their ``pid-N`` owner is
    dead. Live PID runs are protected even when another database is in use.
    """
    result = ScratchPruneResult()
    try:
        global_root = project_scratch_dir.global_scratch_root()
        current_run = project_scratch_dir.scratch_root()
    except project_scratch_dir.ScratchRootResolutionError:
        return result

    active, ended, registry_error = _session_states(conn)
    result.registry_error = registry_error
    if fix and registry_error:
        result.failure_count += 1
        result.issues.append(f"- cleanup refused: {registry_error}")
        return result

    current_session = current_run.parent.parent
    if current_session.name != project_scratch_dir.DEFAULT_SESSION_SEGMENT:
        active.add(current_session.name)
    now = int(time.time()) if now_epoch is None else now_epoch

    for run_dir in _plain_run_dirs(global_root):
        session_dir = run_dir.parent.parent
        pid = _pid_for_run(run_dir)
        pid_alive = pid is not None and _pid_is_alive(pid)
        known_ended = session_dir.name in ended
        unknown_dead_pid = (
            session_dir.name == project_scratch_dir.DEFAULT_SESSION_SEGMENT
            and pid is not None
            and not pid_alive
        )
        if (
            session_dir == current_session
            or session_dir.name in active
            or pid_alive
            or not (known_ended or unknown_dead_pid)
        ):
            result.protected_run_count += 1
            continue

        removed_in_run = False
        cleanup_roots = [
            *(
                (kind, run_dir / kind, threshold)
                for kind, threshold in ORPHAN_AGE_THRESHOLDS_S.items()
            ),
            *(
                (f"storage/{kind}", run_dir / "storage" / kind, threshold)
                for kind, threshold in ORPHAN_STORAGE_AGE_THRESHOLDS_S.items()
            ),
        ]
        for kind, sub_dir, threshold in cleanup_roots:
            if not sub_dir.is_dir() or sub_dir.is_symlink():
                continue
            for entry in _cleanup_entries(kind, sub_dir):
                try:
                    age = now - int(entry.lstat().st_mtime)
                except OSError as exc:
                    result.failure_count += 1
                    result.issues.append(f"- scan failed for {entry}: {exc}")
                    continue
                if age <= threshold:
                    continue
                result.stale_count += 1
                result.issues.append(
                    f"- {entry} ({age // 60}m old, kind={kind})"
                )
                if not fix:
                    continue
                if pid is not None and _pid_is_alive(pid):
                    result.protected_run_count += 1
                    result.issues.append("  -> retained: owning pid became live")
                    break
                try:
                    if entry.is_symlink() or not entry.is_dir():
                        entry.unlink()
                    else:
                        shutil.rmtree(entry)
                    _remove_empty_owned_parents(entry, sub_dir)
                    result.removed_count += 1
                    removed_in_run = True
                    result.issues.append("  -> removed")
                except OSError as exc:
                    result.failure_count += 1
                    result.issues.append(f"  -> removal failed: {exc}")
        if fix and removed_in_run:
            _remove_empty_scaffold(run_dir, result)
    return result


def auto_prune_stale_scratch(
    conn: Any,
    *,
    force: bool = False,
) -> ScratchPruneResult:
    """Run the safe pruner at most once per interval across local processes."""
    try:
        root = project_scratch_dir.global_scratch_root()
    except project_scratch_dir.ScratchRootResolutionError:
        return ScratchPruneResult()
    lock_path = root / ".auto-prune.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return ScratchPruneResult(skipped_throttle=True)
        handle.seek(0)
        stamp = handle.read().strip()
        if not force and stamp:
            try:
                if time.time() - float(stamp) < AUTO_PRUNE_INTERVAL_S:
                    return ScratchPruneResult(skipped_throttle=True)
            except ValueError:
                pass
        result = prune_stale_scratch(conn, fix=True)
        handle.seek(0)
        handle.truncate()
        handle.write(str(time.time()))
        handle.flush()
        return result


__all__ = [
    "AUTO_PRUNE_INTERVAL_S",
    "ORPHAN_AGE_THRESHOLDS_S",
    "ORPHAN_STORAGE_AGE_THRESHOLDS_S",
    "ScratchPruneResult",
    "auto_prune_stale_scratch",
    "prune_stale_scratch",
]
