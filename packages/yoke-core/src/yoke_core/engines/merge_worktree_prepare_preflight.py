"""Preflight checks for merge-worktree preparation."""

from __future__ import annotations

import json
import os
from typing import Optional, Tuple

from typing import TYPE_CHECKING

from yoke_core.domain.classify_dirty_files import is_yoke_managed_pattern

if TYPE_CHECKING:  # the cycle-free half of the prepare<->preflight pair
    from yoke_core.engines.merge_worktree_prepare import MergeContext

# merge_worktree_prepare re-exports preflight_checks at module bottom, so a
# module-top import back into it is order-dependent (whichever module loads
# first wins; the loser sees a partially initialized module). Runtime helpers
# import lazily inside the functions that use them.


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw

def preflight_checks(ctx: MergeContext) -> Optional[Tuple[int, str]]:
    """Run preflight checks. Returns (exit_code, message) on failure, None on success."""
    mw = _parent()
    _print = mw._print
    _run_git = mw._run_git
    _run_python_module = mw._run_python_module

    _print("Running pre-flight checks...")
    fail = False
    exit_code = 1

    # PF-1: Worktree cleanliness
    dirty_tracked = _run_git(["diff", "--name-only"], cwd=ctx.worktree_path, capture=True)
    dirty_untracked = _run_git(
        ["ls-files", "--others", "--exclude-standard"], cwd=ctx.worktree_path, capture=True
    )

    all_dirty = []
    if dirty_tracked.stdout.strip():
        all_dirty.extend(dirty_tracked.stdout.strip().splitlines())
    if dirty_untracked.stdout.strip():
        all_dirty.extend(dirty_untracked.stdout.strip().splitlines())

    yoke_dirty = [f for f in all_dirty if is_yoke_managed_pattern(f)]
    user_dirty = [f for f in all_dirty if not is_yoke_managed_pattern(f)]

    # Auto-commit Yoke-managed files
    if yoke_dirty:
        _print("  Auto-committing Yoke-managed files in worktree...", err=True)
        for sf in yoke_dirty:
            _run_git(["add", sf], cwd=ctx.worktree_path)
        _run_git(
            ["commit", "-m", f"chore: auto-commit Yoke-managed files before merge [{ctx.args.branch}]"],
            cwd=ctx.worktree_path, capture=True,
        )

    if user_dirty:
        _print("  FAIL: Uncommitted non-Yoke files in worktree:", err=True)
        for uf in user_dirty:
            _print(f"    - {uf}", err=True)
        exit_code = 4
        fail = True
    else:
        _print("  OK: Worktree clean (no uncommitted non-Yoke files)")

    # PF-2: Branch tracking
    local_head = _run_git(["rev-parse", "HEAD"], cwd=ctx.worktree_path, capture=True)
    remote_head = _run_git(
        ["rev-parse", f"origin/{ctx.args.branch}"], cwd=ctx.worktree_path, capture=True
    )
    if local_head.returncode == 0 and remote_head.returncode == 0:
        behind = _run_git(
            ["rev-list", f"HEAD..origin/{ctx.args.branch}", "--count"],
            cwd=ctx.worktree_path, capture=True,
        )
        behind_count = int(behind.stdout.strip()) if behind.returncode == 0 else 0
        if behind_count > 0:
            _print(f"  FAIL: Worktree branch is {behind_count} commit(s) behind origin/{ctx.args.branch}", err=True)
            fail = True
        else:
            _print(f"  OK: Branch up to date with origin/{ctx.args.branch}")
    else:
        _print("  OK: Branch tracking check skipped (no remote tracking branch)")

    # PF-3: Epic tasks (when epic ID provided)
    if ctx.epic_id:
        from yoke_core.engines.merge_worktree_prepare import (
            _p,
            _sql_task_terminal_success_list,
        )

        conn = None
        try:
            conn = mw._connect()
            terminal_list = _sql_task_terminal_success_list()
            incomplete = conn.execute(
                f"SELECT task_num, status FROM epic_tasks "
                f"WHERE epic_id={_p(conn)} AND status NOT IN ({terminal_list}) "
                f"ORDER BY task_num",
                (ctx.epic_id,),
            ).fetchall()
            total = conn.execute(
                f"SELECT COUNT(*) FROM epic_tasks WHERE epic_id={_p(conn)}",
                (ctx.epic_id,),
            ).fetchone()[0]

            if total > 0 and incomplete:
                _print("  FAIL: Incomplete tasks found:", err=True)
                for row in incomplete:
                    _print(f"    - {row['task_num']}:{row['status']}", err=True)
                fail = True
            elif total > 0:
                _print("  OK: All tasks completed")
        except Exception:  # noqa: BLE001 - preflight degrades if DB unavailable.
            pass
        finally:
            if conn is not None:
                conn.close()

    # PF-4: Integration simulation gate (epics only)
    if ctx.epic_id:
        result = _run_python_module(
            "yoke_core.cli.db_router",
            ["epic", "simulation-get", str(ctx.epic_id), "integration"],
            capture=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            if ctx.args.skip_simulation:
                _print(f"  WARN: Integration simulation gate overridden (--skip-simulation) for epic: {ctx.epic_id}", err=True)
            else:
                _print(f"  FAIL: Integration simulation report not found for epic: {ctx.epic_id}", err=True)
                _print("    Run /yoke simulate first, or pass --skip-simulation to override.", err=True)
                fail = True
        else:
            _print("  OK: Canonical integration simulation report exists")

    # PF-5: Integration dependency gate
    result = _run_python_module(
        "yoke_core.api.service_client",
        ["evaluate-gate", ctx.args.branch, "integration"],
        capture=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            gate_data = json.loads(result.stdout.strip())
            if gate_data.get("is_blocked"):
                _print(f"  FAIL: Integration dependency gate blocked for {ctx.args.branch}", err=True)
                for b in gate_data.get("unsatisfied_blockers", []):
                    _print(
                        f"    - {b.get('blocking_item', '?')} ({b.get('blocking_status', '?')}): "
                        f"{b.get('rationale', 'no rationale')}",
                        err=True,
                    )
                fail = True
            else:
                _print("  OK: Integration dependency gate clear")
        except (json.JSONDecodeError, TypeError):
            _print("  OK: Integration dependency gate skipped (invalid response)")
    else:
        _print("  OK: Integration dependency gate skipped (service-client unavailable)")

    # PF-6: blocked-flag refusal
    try:
        from yoke_core.domain.advance_blocked_gate import evaluate as _eval_blocked
        from yoke_core.engines.merge_worktree_prepare import _p

        _conn = mw._connect()
        try:
            _row = _conn.execute(
                f"SELECT id FROM items WHERE worktree = {_p(_conn)}",
                (ctx.args.branch,),
            ).fetchone()
            if _row is not None:
                decision = _eval_blocked(_conn, int(_row[0]))
                if decision.blocked:
                    _print(f"  FAIL: Item YOK-{int(_row[0])} is blocked (items.blocked=1).", err=True)
                    if decision.reason:
                        _print(f"    Reason: {decision.reason}", err=True)
                    _print(
                        f"    Run /yoke unblock YOK-{int(_row[0])} before merging.",
                        err=True,
                    )
                    fail = True
                else:
                    _print("  OK: Item not blocked")
        finally:
            _conn.close()
    except Exception:  # noqa: BLE001 - degrade if DB unavailable
        _print("  OK: Blocked-flag gate skipped (DB unavailable)")

    # PF-7: strategy rendered-view drift. `git merge` never enters the
    # commit lint, so branch drift in .yoke/strategy/ views must be
    # refused here before it rides to the target branch.
    strategy_error = _strategy_view_drift_check(ctx, mw)
    if strategy_error:
        for line in strategy_error.splitlines():
            _print(line, err=True)
        fail = True
    else:
        _print("  OK: No strategy rendered-view drift on branch")

    if fail:
        _print("", err=True)
        _print("Pre-flight failed. Fix the issues above before merging.", err=True)
        return (exit_code, "preflight failed")

    _print("Pre-flight checks passed.")
    _print("")
    return None


def _merge_project_id(ctx: MergeContext) -> Optional[int]:
    """Project whose strategy rows govern this merge's rendered views."""
    try:
        from yoke_core.domain import machine_config

        mapped = machine_config.project_id(ctx.repo_root)
        if mapped is not None:
            return int(mapped)
    except Exception:  # noqa: BLE001 - fall through to the item's project
        pass
    if ctx.project:
        try:
            from yoke_core.domain import db_helpers
            from yoke_core.domain.project_identity import resolve_project

            with db_helpers.connect() as conn:
                ident = resolve_project(conn, ctx.project, required=False)
            return ident.id if ident is not None else None
        except Exception:  # noqa: BLE001 - verified fail-closed by caller
            return None
    return None


def _strategy_view_drift_check(ctx: MergeContext, mw) -> Optional[str]:
    """Refuse incoming strategy views that drift from the live rows.

    Fail-closed narrowly (the commit-lint contract): an unreadable row
    set blocks ONLY when the branch actually changes strategy views.
    """
    from yoke_core.domain.lint_main_commit_strategy_freshness import (
        blob_freshness_finding,
        load_project_strategy_rows,
    )
    from yoke_core.domain.strategy_docs_paths import (
        STRATEGY_DIR_REL,
        slug_from_view_path,
    )

    diff = mw._run_git(
        ["diff", "--name-only", f"{ctx.args.target}...HEAD", "--",
         STRATEGY_DIR_REL],
        cwd=ctx.worktree_path, capture=True,
    )
    if diff.returncode != 0:
        return None  # no target ref resolvable here — other gates own that
    slugged = {
        path: slug_from_view_path(path)
        for path in diff.stdout.strip().splitlines()
        if path and slug_from_view_path(path) is not None
    }
    if not slugged:
        return None
    project_id = _merge_project_id(ctx)
    rows, failure = (
        load_project_strategy_rows(project_id, slugged.values())
        if project_id is not None
        else (None, "unmapped checkout — no project context for this repo")
    )
    if rows is None:
        return (
            "  FAIL: branch changes strategy rendered views but their "
            "strategy_docs rows could not be resolved\n"
            f"    ({failure}) — failing closed for "
            "strategy-view changes."
        )
    findings = []
    for path, slug in sorted(slugged.items()):
        show = mw._run_git(
            ["show", f"HEAD:{path}"], cwd=ctx.worktree_path, capture=True,
        )
        blob = show.stdout if show.returncode == 0 else None
        finding = blob_freshness_finding(rows, slug, blob)
        if finding:
            findings.append(finding)
    if not findings:
        return None
    listed = "\n".join(f"    - {finding}" for finding in findings)
    return (
        "  FAIL: branch carries strategy rendered-view drift vs the live "
        "strategy_docs rows:\n"
        f"{listed}\n"
        "    Strategy edits flow through the DB, not ticket branches. "
        "Either ingest the branch's edit\n"
        "    (`yoke strategy ingest <SLUG> --target-root "
        f"{ctx.worktree_path or '<worktree>'}`, then commit the re-stamped "
        "render),\n"
        "    or drop the file edit on the branch and re-render after merge."
    )
