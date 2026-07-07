"""QA gate helper functions — shared utilities for qa_gates.py.

Extracted from qa_gates.py to keep that module under the 800-line
target.  Contains: table-existence check, branch/project resolution, latest
code-ref resolution, code-identity extraction, and browser-freshness helpers.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import List, Optional, Tuple

from yoke_core.domain.db_helpers import connect, query_one, query_rows, query_scalar
from yoke_core.domain.project_checkout_locations import checkout_for_project
from yoke_core.domain.qa_gate_definitions import GateTarget, LatestCodeRef
from yoke_core.domain.schema_common import _table_exists


def _qa_tables_exist(db_path: str) -> bool:
    """Check if qa_requirements table exists (graceful pre-migration)."""
    conn = connect(db_path)
    try:
        return _table_exists(conn, "qa_requirements")
    finally:
        conn.close()


def _resolve_target_branch_project(
    target: GateTarget, db_path: str
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve the target branch and project for freshness checks."""
    conn = connect(db_path)
    try:
        branch = None
        project = None

        if target.item_id is not None:
            try:
                row = query_one(
                    conn,
                    "SELECT i.worktree, p.slug AS project "
                    "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
                    "WHERE i.id = %s",
                    (target.item_id,),
                )
                if row:
                    branch = row["worktree"]
                    project = row["project"]
            except Exception:
                return None, None
        elif target.epic_id is not None:
            try:
                branch_row = query_one(
                    conn,
                    "SELECT branch FROM epic_tasks WHERE epic_id = %s AND task_num = %s",
                    (target.epic_id, target.task_num),
                )
                if branch_row:
                    branch = branch_row["branch"]
                if not branch:
                    item_row = query_one(
                        conn,
                        "SELECT worktree FROM items WHERE id = %s",
                        (target.epic_id,),
                    )
                    if item_row:
                        branch = item_row["worktree"]
                proj_row = query_one(
                    conn,
                    "SELECT p.slug AS project "
                    "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
                    "WHERE i.id = %s",
                    (target.epic_id,),
                )
                if proj_row:
                    project = proj_row["project"]
            except Exception:
                return None, None
    finally:
        conn.close()

    return branch, project


def _resolve_latest_code_ref(
    target: GateTarget, db_path: str
) -> LatestCodeRef:
    """Resolve the latest branch / SHA / timestamp on the target branch."""
    override_ts = os.environ.get("YOKE_QA_GATE_COMMIT_TS")
    override_sha = os.environ.get("YOKE_QA_GATE_COMMIT_SHA")
    override_branch = os.environ.get("YOKE_QA_GATE_BRANCH")
    if override_ts or override_sha or override_branch:
        return LatestCodeRef(
            branch=override_branch or None,
            sha=override_sha or None,
            timestamp=override_ts or None,
        )

    branch, project = _resolve_target_branch_project(target, db_path)
    if not branch or branch == "null":
        return LatestCodeRef()

    checkout_path = None
    if project and project != "null":
        conn = connect(db_path)
        try:
            checkout = checkout_for_project(conn, project)
            checkout_path = str(checkout) if checkout is not None else None
        except Exception:
            pass
        finally:
            conn.close()

    if not checkout_path:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                checkout_path = result.stdout.strip()
        except Exception:
            return LatestCodeRef(branch=branch)

    if not checkout_path:
        return LatestCodeRef(branch=branch)

    git_dir = os.path.join(checkout_path, ".worktrees", branch)
    if not os.path.isdir(git_dir):
        git_dir = checkout_path

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                git_dir,
                "log",
                "-1",
                "--format=%H|%cd",
                "--date=format:%Y-%m-%dT%H:%M:%SZ",
                branch,
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "TZ": "UTC"},
        )
        if result.returncode == 0 and result.stdout.strip():
            sha, _, timestamp = result.stdout.strip().partition("|")
            return LatestCodeRef(
                branch=branch,
                sha=sha or None,
                timestamp=timestamp or None,
            )
    except Exception:
        pass

    return LatestCodeRef(branch=branch)


def _resolve_latest_commit_ts(
    target: GateTarget, db_path: str
) -> Optional[str]:
    """Backwards-compatible wrapper returning only the latest commit timestamp."""
    return _resolve_latest_code_ref(target, db_path).timestamp


def _resolve_repo_root() -> Optional[str]:
    """Resolve the git repo root."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _extract_code_identity(raw_result: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Extract browser QA code identity from raw_result JSON when present."""
    if not raw_result:
        return None, None
    try:
        payload = json.loads(raw_result)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    code_identity = payload.get("code_identity")
    if not isinstance(code_identity, dict):
        return None, None
    branch = code_identity.get("branch")
    sha = code_identity.get("sha")
    return (
        str(branch) if branch else None,
        str(sha) if sha else None,
    )


def _browser_run_is_fresh(run_row, latest_code: LatestCodeRef) -> bool:
    """Return True when a passing browser run matches the latest code."""
    _, run_sha = _extract_code_identity(run_row["raw_result"])
    if latest_code.sha and run_sha == latest_code.sha:
        return True
    created_at = run_row["created_at"] or ""
    if latest_code.timestamp and created_at >= latest_code.timestamp:
        return True
    return False


def _latest_browser_run(conn, requirement_id: int):
    """Return the latest passing browser-substrate run for a requirement."""
    return query_one(
        conn,
        """
        SELECT id, created_at, raw_result
        FROM qa_runs
        WHERE qa_requirement_id = %s
          AND verdict = 'pass'
          AND executor_type <> 'agent'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (requirement_id,),
    )


def _collect_stale_browser_requirements(
    conn,
    *,
    where: str,
    params: tuple,
    latest_code: LatestCodeRef,
    qa_phase: Optional[str] = "verification",
) -> List[Tuple[int, str, Optional[str], Optional[str]]]:
    """Return browser requirements whose latest pass does not match latest code."""
    phase_sql = ""
    phase_params: tuple = ()
    if qa_phase is not None:
        phase_sql = "AND r.qa_phase = %s"
        phase_params = (qa_phase,)
    req_rows = query_rows(
        conn,
        f"""
        SELECT r.id, r.qa_kind
        FROM qa_requirements r
        WHERE {where}
          {phase_sql}
          AND r.blocking_mode = 'blocking'
          AND r.waived_at IS NULL
          AND r.qa_kind IN ('browser_smoke', 'browser_diff')
          AND EXISTS (
            SELECT 1 FROM qa_runs qr
            WHERE qr.qa_requirement_id = r.id
              AND qr.verdict = 'pass'
              AND qr.executor_type <> 'agent'
          )
        """,
        (*params, *phase_params),
    )
    stale: List[Tuple[int, str, Optional[str], Optional[str]]] = []
    for row in req_rows:
        latest_run = _latest_browser_run(conn, int(row["id"]))
        if latest_run is None:
            continue
        if _browser_run_is_fresh(latest_run, latest_code):
            continue
        _, run_sha = _extract_code_identity(latest_run["raw_result"])
        stale.append(
            (
                int(row["id"]),
                str(row["qa_kind"]),
                str(latest_run["created_at"] or "") or None,
                run_sha,
            )
        )
    return stale


def _browser_freshness_errors(
    *,
    name: str,
    transition_name: str,
    latest_code: LatestCodeRef,
    stale_rows: List[Tuple[int, str, Optional[str], Optional[str]]],
    bypass_hint: Optional[str] = None,
) -> List[str]:
    """Build a user-facing stale browser evidence error block."""
    errors = [
        f"Error: Cannot transition {name} to '{transition_name}' -- {len(stale_rows)} browser requirement(s) have only stale passing runs.",
        "  Browser runs must match the latest code on the branch.",
    ]
    if latest_code.branch:
        errors.append(f"  Branch: {latest_code.branch}")
    if latest_code.sha:
        errors.append(f"  Latest SHA: {latest_code.sha}")
    if latest_code.timestamp:
        errors.append(f"  Latest commit: {latest_code.timestamp}")
    errors.append("  Re-run browser scenarios to generate fresh passing runs.")
    if bypass_hint:
        errors.append(bypass_hint)
    for req_id, qa_kind, latest_run_at, run_sha in stale_rows:
        detail = (
            f"  - Requirement #{req_id} ({qa_kind}): latest passing run at "
            f"{latest_run_at or '<unknown>'}"
        )
        if run_sha:
            detail += f", run SHA {run_sha}"
        errors.append(detail)
    return errors
