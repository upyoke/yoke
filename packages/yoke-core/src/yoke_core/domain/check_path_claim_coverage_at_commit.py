"""Pre-commit path-claim coverage enforcement.

Worktree commits are refused when staged files exceed an active claim.
Main-checkout commits, claimless items, and unresolved sessions are no-ops.
The commit-message suppression token emits durable warning evidence.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.lint_worktree_path_invariants import (
    WorktreeInvariantContext,
    resolve_active_worktree_context,
)
from yoke_core.domain.path_claim_commit_coverage import (
    declared_targets_for_claim,
    effective_commit_targets,
)


_SUPPRESSION_TOKEN = "[no-path-claim-check]"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def staged_files(repo_root: Path) -> list[str]:
    """Return ``git diff --cached --name-only`` for *repo_root*.

    Empty list when git is unavailable or the diff returns nothing.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def files_outside_coverage(
    staged_paths: Iterable[str],
    declared_paths: Sequence[str],
    declared_target_kinds: Sequence[tuple[str, str]] = (),
) -> list[str]:
    """Return staged paths not covered by *declared_paths*.

    A staged path is covered when it matches a declared path exactly OR
    sits inside a declared directory prefix (declared paths ending with
    ``/`` are treated as directory-prefix matchers). Order is preserved
    from the input.
    """
    kind_by_path = dict(declared_target_kinds)
    declared_files = {
        p for p in declared_paths if p and kind_by_path.get(p, "file") != "directory"
    }
    declared_dirs = [
        p.rstrip("/") + "/"
        for p in declared_paths
        if p
        and (
            kind_by_path.get(p) == "directory"
            or (not declared_target_kinds and p.endswith("/"))
        )
    ]
    out: list[str] = []
    for path in staged_paths:
        if path in declared_files:
            continue
        if any(path.startswith(prefix) for prefix in declared_dirs):
            continue
        out.append(path)
    return out


def find_active_claim_for_item(
    conn: Any,
    item_id: int,
) -> Optional[dict]:
    """Return the most recent non-terminal path-claim row for *item_id*.

    Order: ``active`` first (one is held at most), then ``planned`` /
    ``blocked`` by id desc. Returns ``None`` when no non-terminal claim
    exists.
    """
    try:
        p = _p(conn)
        row = conn.execute(
            "SELECT id, state FROM path_claims "
            f"WHERE owner_kind = 'item' AND owner_item_id = {p} "
            "AND state IN ('planned','blocked','active') "
            "ORDER BY CASE state WHEN 'active' THEN 0 "
            "                  WHEN 'planned' THEN 1 "
            "                  WHEN 'blocked' THEN 2 END, id DESC "
            "LIMIT 1",
            (int(item_id),),
        ).fetchone()
    except db_backend.operational_error_types(conn=conn):
        return None
    if row is None:
        return None
    claim_id = int(row["id"] if hasattr(row, "keys") else row[0])
    state = str(row["state"] if hasattr(row, "keys") else row[1])
    try:
        declared_paths, declared_target_kinds = declared_targets_for_claim(
            conn,
            claim_id,
        )
    except db_backend.operational_error_types(conn=conn):
        return None
    return {
        "claim_id": claim_id,
        "state": state,
        "declared_paths": declared_paths,
        "declared_target_kinds": declared_target_kinds,
    }


def _resolve_git_dir(repo_root: Path) -> Optional[Path]:
    """Regular ``.git`` dir or linked-worktree ``gitdir:`` file; ``None`` otherwise."""
    entry = repo_root / ".git"
    if entry.is_dir():
        return entry
    try:
        text = entry.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not text.startswith("gitdir:"):
        return None
    target = text[len("gitdir:") :].strip().splitlines()
    if not target:
        return None
    path = Path(target[0].strip())
    if not path.is_absolute():
        path = (repo_root / path).resolve()
    return path


def read_commit_message(repo_root: Path) -> str:
    """Best-effort COMMIT_EDITMSG read via :func:`_resolve_git_dir`; ``""`` on error."""
    git_dir = _resolve_git_dir(repo_root)
    if git_dir is None:
        return ""
    try:
        return (git_dir / "COMMIT_EDITMSG").read_text(encoding="utf-8")
    except Exception:
        return ""


def has_suppression_token(message: str) -> bool:
    return _SUPPRESSION_TOKEN in (message or "")


def _record_suppression_event(
    item_id: int,
    claim_id: int,
    missing_paths: Sequence[str],
) -> None:
    """Emit a suppression-evidence event. Best-effort; never raises."""
    try:
        from yoke_core.domain import events as events_mod
    except Exception:
        return
    try:
        events_mod.emit_event(
            "PathClaimCoverageSuppressed",
            event_kind="hook",
            event_type="lint_decision",
            severity="WARN",
            outcome="suppressed",
            item_id=str(item_id),
            context={
                "claim_id": claim_id,
                "missing_paths": list(missing_paths),
                "suppression_token": _SUPPRESSION_TOKEN,
            },
        )
    except Exception:
        return


def format_deny(
    *,
    item_id: int,
    claim_id: int,
    missing_paths: Sequence[str],
    declared_paths: Sequence[str],
) -> str:
    """Render the operator-facing block message for a coverage refusal."""
    lines: list[str] = [
        "ERROR: pre-commit refused — staged files exceed the active "
        f"path-claim coverage for YOK-{item_id} (claim id {claim_id}).",
        "",
        "Files outside declared coverage:",
    ]
    for path in missing_paths:
        lines.append(f"  - {path}")
    lines.append("")
    lines.append("Currently declared coverage:")
    for path in declared_paths:
        lines.append(f"  - {path}")
    lines.append("")
    lines.append("Remediation — widen the active claim:")
    lines.append("")
    lines.append("  python3 -m yoke_core.cli.db_router path-claims widen \\")
    lines.append(f"      {claim_id} \\")
    paths_csv = ",".join(missing_paths)
    lines.append(f"      --paths '{paths_csv}' \\")
    lines.append("      --reason '<why this widen is needed>'")
    lines.append("")
    lines.append(
        "Operator escape hatch: include "
        f"'{_SUPPRESSION_TOKEN}' in the commit message body, or "
        "use 'git commit --no-verify'."
    )
    return "\n".join(lines) + "\n"


def _open_conn() -> Optional[Any]:
    try:
        return db_helpers.connect()
    except db_backend.operational_error_types() + (RuntimeError,):
        return None


def _resolve_repo_root() -> Optional[Path]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    return Path(root) if root else None


def _decide(
    *,
    ctx: Optional[WorktreeInvariantContext],
    repo_root: Path,
    conn: Any,
    commit_message: str,
) -> tuple[int, str]:
    """Pure decision body. Returns (rc, stderr-message)."""
    if ctx is None or not ctx.is_inside_worktree:
        return 0, ""
    if ctx.item_id is None:
        return 0, ""
    claim = find_active_claim_for_item(conn, ctx.item_id)
    if claim is None:
        return 0, ""
    staged = staged_files(repo_root)
    if not staged:
        return 0, ""
    paths, kinds = effective_commit_targets(
        conn,
        session_id=ctx.session_id,
        item_id=ctx.item_id,
        repo_root=repo_root,
        declared_paths=claim["declared_paths"],
        declared_target_kinds=claim["declared_target_kinds"],
    )
    claim["declared_paths"] = paths
    claim["declared_target_kinds"] = kinds
    missing = files_outside_coverage(
        staged,
        claim["declared_paths"],
        claim["declared_target_kinds"],
    )
    if not missing:
        return 0, ""
    if has_suppression_token(commit_message):
        _record_suppression_event(
            item_id=ctx.item_id,
            claim_id=claim["claim_id"],
            missing_paths=missing,
        )
        return 0, ""
    return 1, format_deny(
        item_id=ctx.item_id,
        claim_id=claim["claim_id"],
        missing_paths=missing,
        declared_paths=claim["declared_paths"],
    )


def main(argv: list[str] | None = None) -> int:
    """Pre-commit body. ``argv`` is unused but accepted for symmetry."""
    parser = argparse.ArgumentParser(
        description="Path-claim coverage check for pre-commit."
    )
    parser.parse_args(argv or [])
    repo_root = _resolve_repo_root()
    if repo_root is None:
        return 0
    ctx = resolve_active_worktree_context(cwd=str(repo_root))
    if ctx is None or not ctx.is_inside_worktree:
        return 0
    conn = _open_conn()
    if conn is None:
        return 0
    try:
        rc, message = _decide(
            ctx=ctx,
            repo_root=repo_root,
            conn=conn,
            commit_message=read_commit_message(repo_root),
        )
    finally:
        conn.close()
    if message:
        sys.stderr.write(message)
    return rc


__all__ = [
    "files_outside_coverage",
    "find_active_claim_for_item",
    "format_deny",
    "has_suppression_token",
    "main",
    "read_commit_message",
    "staged_files",
]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
