"""Merge and cleanup operations for done-transition."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import Optional, Tuple


def _parent():
    from yoke_core.engines import done_transition as _dt
    return _dt

def _cross_project_commit_guard(
    item_id: int, item_project: str, repo_root: Optional[Path] = None,
) -> None:
    """Advisory cross-project commit guard (scans the Yoke repo)."""
    if item_project == "yoke":
        return
    print("\n=== Step 5c: Cross-project commit guard ===")
    from yoke_core.domain import project_settings

    base_br = project_settings.get_project_str(repo_root, "base_branch")
    log_result = _parent()._run_git(
        ["log", base_br, "--oneline", f"--grep=YOK-{item_id}",
         "--format=%H"],
        capture=True,
    )
    if not log_result.stdout or not log_result.stdout.strip():
        print("No cross-project commit contamination detected.")
        return
    warnings = []
    for commit_hash in log_result.stdout.strip().split("\n"):
        if not commit_hash.strip():
            continue
        files_result = _parent()._run_git(
            ["diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
            capture=True,
        )
        bad_files = []
        for f in (files_result.stdout or "").strip().split("\n"):
            f = f.strip()
            if not f:
                continue
            # Bookkeeping allowlist
            if any(f.startswith(p) for p in [
                "ouroboros/", ".agents/", ".claude/",
            ]):
                continue
            bad_files.append(f)
        if bad_files:
            short = commit_hash[:10]
            msg_result = _parent()._run_git(
                ["log", "--format=%s", "-1", commit_hash], capture=True
            )
            msg = (msg_result.stdout or "").strip()
            warnings.append((short, msg, bad_files))
    if warnings:
        print(f"\nWARNING: Cross-project commit contamination detected for "
              f"YOK-{item_id} (project={item_project}).")
        for short, msg, files in warnings:
            print(f"  Commit {short} ({msg}):")
            for f in files:
                print(f"    {f}")
    else:
        print("No cross-project commit contamination detected.")


def _pre_merge_commit(repo_root: Path) -> None:
    """Pre-merge commit of Yoke-managed files."""
    from yoke_core.domain.classify_dirty_files import is_yoke_managed_pattern

    status = _parent()._run_git(["status", "--porcelain"], cwd=repo_root, capture=True)
    if not status.stdout or not status.stdout.strip():
        return
    yoke_files = []
    for line in status.stdout.strip().split("\n"):
        if len(line) < 4:
            continue
        filepath = line[3:].strip()
        if is_yoke_managed_pattern(filepath):
            yoke_files.append(filepath)
    if yoke_files:
        for f in yoke_files:
            _parent()._run_git(["add", f], cwd=repo_root, capture=True)
        # Check if there's anything staged
        diff = _parent()._run_git(["diff", "--cached", "--quiet"], cwd=repo_root, capture=True)
        if diff.returncode != 0:
            _parent()._run_git(
                ["commit", "-m",
                 "chore: auto-commit Yoke bookkeeping before merge"],
                cwd=repo_root,
            )
            print("Pre-merge commit: Yoke-managed files committed.")


def _do_merge(
    item_id: int,
    lane_branch: str,
    base_branch: str,
    task_parent_ref: str,
    project_repo: Path,
) -> Tuple[int, str, bool]:
    """Execute merge-worktree. Returns (exit_code, output, merge_ran)."""
    # Resolve actual branch from worktree directory. Lanes live at
    # .worktrees/<branch>, so locate the directory from the recorded branch
    # (public ref or legacy name) rather than reconstructing YOK-{internal_id}.
    from yoke_core.domain.worktree_naming import worktree_name_for_item

    actual_branch = lane_branch
    wt_name = lane_branch or worktree_name_for_item(None, item_id)
    wt_dir = project_repo / ".worktrees" / wt_name
    if wt_dir.is_dir():
        br = _parent()._run_git(["-C", str(wt_dir), "branch", "--show-current"], capture=True)
        actual = (br.stdout or "").strip()
        if actual and actual != lane_branch:
            print(f"Warning: branch mismatch for YOK-{item_id}", file=sys.stderr)
            print(f"  Stored:  {lane_branch}", file=sys.stderr)
            print(f"  Actual:  {actual}", file=sys.stderr)
            print("  Using actual branch for merge.", file=sys.stderr)
            actual_branch = actual

    print(f"\n--- Merging branch: {actual_branch} -> {base_branch} ---")
    from yoke_core.engines.merge_worktree import MergeArgs, run as merge_run

    # A branch with no epic lane is a standalone item merge, and every one of
    # those routes through the same boundary so the merge lock, telemetry, and
    # merged_at stamp land the same way regardless of caller.
    if not task_parent_ref:
        from yoke_core.domain.standalone_item_merge import (
            merge_standalone_branch,
        )

        outcome = merge_standalone_branch(
            item_id=item_id,
            branch=actual_branch,
            target=base_branch,
            repo_root=str(project_repo),
            local_merge=False,
        )
        for warning in outcome.warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        return outcome.exit_code, outcome.output, outcome.ok

    # Capture merge output for YOKE_REPO_ROOT parsing by the re-verify step.
    captured = io.StringIO()
    saved_stdout = sys.stdout
    sys.stdout = _parent()._Tee(saved_stdout, captured)
    try:
        merge_args = MergeArgs(
            branch=actual_branch,
            target=base_branch,
            epic_ref=task_parent_ref,
            local_merge=False,
            force_lock=False,
            keep_remote=False,
            skip_simulation=False,
        )
        rc = merge_run(merge_args)
    finally:
        sys.stdout = saved_stdout
    return rc, captured.getvalue(), rc == 0


def _verify_cwd_after_merge(
    merge_ran: bool, merge_output: str, project_repo: Path
) -> Optional[Path]:
    """Re-verify CWD after merge (step 5). Returns updated repo root or None on error."""
    from yoke_core.engines.done_transition_gates import _resolve_repo_root

    print("\n=== Step 5: Re-verify CWD ===")
    if merge_ran:
        # Parse YOKE_REPO_ROOT from merge output
        for line in (merge_output or "").split("\n"):
            if line.startswith("YOKE_REPO_ROOT="):
                parsed = line.split("=", 1)[1].strip()
                if parsed and Path(parsed).is_dir():
                    os.chdir(parsed)
                    break
        else:
            root = _resolve_repo_root()
            if root:
                os.chdir(root)
    cwd = Path.cwd()
    if "/.worktrees/" in str(cwd):
        print("Error: CWD is inside a worktree after merge. Cannot continue.",
              file=sys.stderr)
        return None
    print(f"CWD verified: {cwd}")

    # Verify main repo is on main/master branch
    br = _parent()._run_git(["-C", str(project_repo), "rev-parse", "--abbrev-ref", "HEAD"],
                   capture=True)
    current = (br.stdout or "").strip()
    if current and current not in ("main", "master", "HEAD"):
        print(f"Warning: Main repo is on branch '{current}', not main. "
              "Switching to main.")
        # Stash if dirty
        stashed = False
        st = _parent()._run_git(["-C", str(project_repo), "status", "--porcelain"],
                       capture=True)
        if st.stdout and st.stdout.strip():
            _parent()._run_git(["-C", str(project_repo), "stash", "push",
                       "--include-untracked", "-m", "yoke-step5-branch-fix"],
                      capture=True)
            stashed = True
        co = _parent()._run_git(["-C", str(project_repo), "checkout", "main"], capture=True)
        if co.returncode != 0:
            _parent()._run_git(["-C", str(project_repo), "checkout", "master"], capture=True)
        else:
            print("Switched to main.")
        if stashed:
            _parent()._run_git(["-C", str(project_repo), "stash", "pop"], capture=True)
    else:
        print(f"Branch verified: {current}")
    return cwd


_SCHEMA_GATE_PREFIXES = (
    "runtime/api/domain/schema",
    "runtime/api/domain/shepherd",
    "runtime/api/domain/migration",
)

def _schema_gate(*, merge_ran: bool = True, project_repo: Path | None = None) -> None:
    """Post-merge schema refresh (step 5a).

    Over an https control plane the server owns and converges its own
    schema on boot; there is no local DB to re-converge and re-converging
    the server's schema from the client is neither possible nor correct, so
    the refresh (schema + shepherd init) is skipped. On a local Postgres
    connection the merge just updated the schema source on disk, so the
    local DB is re-converged in-process exactly as before.
    """
    from yoke_core.domain import schema as _schema_domain, shepherd as _shepherd_domain
    from yoke_core.domain.worktree_create_db import item_worktree_authority_is_https

    print("\n=== Step 5a: Schema gate ===")
    if not _schema_gate_needed(merge_ran, project_repo):
        print("[schema-gate] schema current - skipping refresh.")
        return
    if item_worktree_authority_is_https():
        print(
            "[schema-gate] Skipping schema refresh over https "
            "(server owns its own schema)."
        )
        return
    print("[schema-gate] Running schema refresh...")
    try:
        _schema_domain.cmd_init()
        print("[schema-gate] schema.cmd_init: ok")
    except Exception as exc:
        print(f"[schema-gate] schema.cmd_init: Warning: failed (non-fatal): {exc}")
    try:
        with _parent()._connect() as conn:
            _shepherd_domain.cmd_init(conn)
        print("[schema-gate] shepherd.cmd_init: ok")
    except Exception as exc:
        print(f"[schema-gate] shepherd.cmd_init: Warning: failed (non-fatal): {exc}")
    print("[schema-gate] Schema refresh complete.")


def _schema_gate_needed(merge_ran: bool, project_repo: Path | None) -> bool:
    if os.environ.get("YOKE_SCHEMA_GATE_FORCE") == "1":
        return True
    if not merge_ran:
        return False
    repo = project_repo or _parent()._resolve_repo_root()
    changed = _parent()._run_git(
        ["-C", str(repo), "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "HEAD"],
        capture=True,
    )
    if changed.returncode != 0:
        return True
    paths = (line.strip() for line in (changed.stdout or "").splitlines())
    return any(path.startswith(_SCHEMA_GATE_PREFIXES) for path in paths if path)

def _handle_already_done(
    item_id: int, project_repo: Path, result, result_file: str
) -> int:
    """Handle already-completed items with a tiny idempotent fast path."""
    print(f"Pre-flight: YOK-{item_id} is already completed (status=done, "
          "worktree cleared).")
    print("No cleanup or discovery work needed on idempotent re-run.")
    result.already_completed = True
    result.new_status = "done"
    result.write(result_file)
    print(f"RESULT_FILE={result_file}")
    return 0
