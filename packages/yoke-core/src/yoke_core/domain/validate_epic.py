"""Deterministic integrity checks for a Yoke epic.

Backs the public ``validate.sh`` CLI surface while keeping the semantic owner
in Python. The shell entrypoint should remain a thin boundary that resolves the
target repo root and execs this module.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, TextIO

from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
from yoke_core.domain.lifecycle import TASK_TERMINAL_SUCCESS
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)
from yoke_core.domain.validate_epic_context import (
    _ACTIVE_TASK_STATUSES,
    ValidateContext,
    _connect,
    _int_scalar,
    _parse_timestamp,
    _p,
    _resolve_epic,
    _result,
    _terminal_success_placeholders,
)


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env)


def _issue_accessible_via_rest(
    repo: str, issue_num: str, *, token: str
) -> bool:
    """Return True when ``GET /repos/<owner>/<name>/issues/<n>`` responds 200.

    Routes via the canonical PAT-backed REST transport.
    """
    if not repo or not issue_num:
        return False
    try:
        owner, name = split_repo(repo)
    except ValueError:
        return False
    req = RestRequest(method="GET", path=f"/repos/{owner}/{name}/issues/{issue_num}")
    try:
        request_with_retry(req, token=token)
    except RestTransportError:
        return False
    return True


def run_validation(repo_root: Path, epic_ref: str, *, out: TextIO, err: TextIO) -> int:
    ctx = ValidateContext(repo_root=repo_root)

    with _connect() as conn:
        try:
            display_ref, canonical_epic_id, gh_repo = _resolve_epic(conn, epic_ref)
        except ValueError as exc:
            err.write(f"Error: {exc}\n")
            return 1

        task_count = _int_scalar(
            conn,
            f"SELECT COUNT(*) FROM epic_tasks WHERE epic_id={_p(conn)}",
            (canonical_epic_id,),
        )
        if task_count == 0:
            err.write(f"Error: Epic '{canonical_epic_id}' has no tasks in DB\n")
            return 1

        issues = 0
        warnings = 0
        passed = 0

        out.write(f"Validation: {display_ref} ({canonical_epic_id})\n\n")

        placeholders = _terminal_success_placeholders(conn)
        terminal_params = tuple(sorted(TASK_TERMINAL_SUCCESS))

        check1_ok = True
        total = _int_scalar(
            conn,
            f"SELECT COUNT(*) FROM epic_tasks WHERE epic_id={_p(conn)}",
            (canonical_epic_id,),
        )
        done_count = _int_scalar(
            conn,
            "SELECT COUNT(*) FROM epic_tasks "
            f"WHERE epic_id={_p(conn)} AND status IN ({placeholders})",
            (canonical_epic_id, *terminal_params),
        )
        pending_count = _int_scalar(
            conn,
            "SELECT COUNT(*) FROM epic_tasks "
            f"WHERE epic_id={_p(conn)} AND status IN ('planning','planned')",
            (canonical_epic_id,),
        )
        in_progress = _int_scalar(
            conn,
            "SELECT COUNT(*) FROM epic_tasks "
            f"WHERE epic_id={_p(conn)} AND status='implementing'",
            (canonical_epic_id,),
        )
        null_status = _int_scalar(
            conn,
            "SELECT COUNT(*) FROM epic_tasks "
            f"WHERE epic_id={_p(conn)} AND (status IS NULL OR status='')",
            (canonical_epic_id,),
        )
        if null_status > 0:
            _result(out, "❌", f"Task status: {null_status} tasks with NULL/empty status")
            issues += 1
            check1_ok = False
        if check1_ok:
            _result(
                out,
                "✅",
                f"Task status distribution: {total} total ({done_count} done, {in_progress} implementing, {pending_count} pending)",
            )
            passed += 1

        check2_ok = True
        checked_worktrees = False
        worktree_rows = conn.execute(
            f"""
            SELECT DISTINCT worktree
              FROM epic_tasks
             WHERE epic_id={_p(conn)}
               AND status NOT IN ({placeholders})
               AND worktree IS NOT NULL
               AND worktree <> ''
            """,
            (canonical_epic_id, *terminal_params),
        ).fetchall()
        git_worktrees = _run(["git", "worktree", "list"], cwd=repo_root).stdout
        for row in worktree_rows:
            worktree = (row["worktree"] or "").strip()
            if not worktree:
                continue
            checked_worktrees = True
            if worktree not in git_worktrees:
                _result(out, "❌", f"Worktree missing: {worktree}")
                issues += 1
                check2_ok = False
        if check2_ok:
            _result(out, "✅", "Worktrees: all present" if checked_worktrees else "Worktrees: none expected")
            passed += 1

        check3_ok = True
        check3_skipped = False
        rest_token: Optional[str] = None
        project = conn.execute(
            "SELECT COALESCE(p.slug, 'yoke') FROM items i "
            "LEFT JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id={_p(conn)} LIMIT 1",
            (canonical_epic_id,),
        ).fetchone()
        project_id = str(project[0] or "yoke") if project else "yoke"
        try:
            auth = resolve_project_github_auth(project_id, conn=conn)
        except ProjectGithubAuthError as exc:
            _result(out, "🚨", f"GitHub checks: skipped ({exc.code})")
            warnings += 1
            check3_skipped = True
        else:
            rest_token = auth.token
            gh_repo = auth.repo
        if not check3_skipped and rest_token:
            checked_gh = False
            gh_rows = conn.execute(
                f"""
                SELECT task_num, github_issue
                  FROM epic_tasks
                 WHERE epic_id={_p(conn)}
                   AND github_issue IS NOT NULL
                   AND github_issue <> ''
                """,
                (canonical_epic_id,),
            ).fetchall()
            for row in gh_rows:
                gh_issue = str(row["github_issue"] or "").strip()
                if not gh_issue or gh_issue == "null":
                    continue
                checked_gh = True
                issue_num = gh_issue.lstrip("#")
                if not _issue_accessible_via_rest(gh_repo, issue_num, token=rest_token):
                    _result(out, "❌", f"GitHub issue {gh_issue} not found (task {row['task_num']})")
                    issues += 1
                    check3_ok = False
            if check3_ok:
                _result(out, "✅", "GitHub issues: all accessible" if checked_gh else "GitHub issues: none linked")
                passed += 1

        check4_ok = True
        dup_count = _int_scalar(
            conn,
            f"""
            SELECT COUNT(*)
              FROM (
                    SELECT task_num, COUNT(*) AS cnt
                      FROM epic_tasks
                     WHERE epic_id={_p(conn)}
                  GROUP BY task_num
                    HAVING COUNT(*) > 1
                   ) AS dup
            """,
            (canonical_epic_id,),
        )
        if dup_count > 0:
            _result(out, "❌", f"Task numbering: {dup_count} duplicate task_num values")
            issues += 1
            check4_ok = False

        no_title = _int_scalar(
            conn,
            "SELECT COUNT(*) FROM epic_tasks "
            f"WHERE epic_id={_p(conn)} AND (title IS NULL OR title='')",
            (canonical_epic_id,),
        )
        if no_title > 0:
            _result(out, "🚨", f"Task titles: {no_title} tasks with missing titles")
            warnings += 1
            check4_ok = False

        if check4_ok:
            _result(out, "✅", "Task data integrity: consistent")
            passed += 1

        check5_ok = True
        checked_heartbeats = False
        hb_rows = conn.execute(
            f"""
            SELECT task_num, title, status, last_heartbeat
              FROM epic_tasks
             WHERE epic_id={_p(conn)}
               AND status IN ({_p(conn)}, {_p(conn)})
               AND last_heartbeat IS NOT NULL
            """,
            (canonical_epic_id, *_ACTIVE_TASK_STATUSES),
        ).fetchall()
        now = datetime.now(timezone.utc)
        for row in hb_rows:
            hb = _parse_timestamp(str(row["last_heartbeat"] or ""))
            if hb is None:
                continue
            checked_heartbeats = True
            age_min = int((now - hb).total_seconds() // 60)
            if age_min > 30:
                _result(
                    out,
                    "🚨",
                    f"Task {row['task_num']} ({row['title']}): {row['status']} for {age_min} min (may be stale)",
                )
                warnings += 1
                check5_ok = False
        if check5_ok:
            _result(
                out,
                "✅",
                "In-progress tasks: heartbeats fresh" if checked_heartbeats else "In-progress tasks: none active",
            )
            passed += 1

        out.write(f"\nResults: {passed} passed, {warnings} warnings, {issues} issues\n")
        return 1 if issues > 0 else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate",
        description="Validate Yoke epic task integrity",
        add_help=True,
    )
    parser.add_argument("--repo-root", default=os.getcwd(), help="Target repo root")
    parser.add_argument("epic_ref", nargs="?")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.epic_ref:
        print("Usage: validate.sh <epic-ref>", file=sys.stderr)
        return 1
    return run_validation(Path(args.repo_root), args.epic_ref, out=sys.stdout, err=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
