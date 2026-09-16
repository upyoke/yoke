"""QA gate helper functions — shared utilities for qa_gates.py.

Extracted from qa_gates.py to keep that module under the 800-line
target.  Contains: table-existence check, branch/project resolution, latest
code-ref resolution, code-identity extraction, and browser-freshness helpers.
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional, Tuple

from yoke_core.domain.db_helpers import connect, query_one, query_rows
from yoke_core.domain.item_worktree_resolution import (
    primary_item_worktree_branch_sql,
)
from yoke_core.domain.project_checkout_locations import checkout_for_project
from yoke_core.domain.qa_constants import INVALID_BROWSER_METHOD_LABEL
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
                    "SELECT "
                    f"{primary_item_worktree_branch_sql('i.id')} AS branch, "
                    "p.slug AS project "
                    "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
                    "WHERE i.id = %s",
                    (target.item_id,),
                )
                if row:
                    branch = row["branch"]
                    project = row["project"]
            except Exception:
                return None, None
        elif target.epic_id is not None:
            try:
                branch_row = query_one(
                    conn,
                    "SELECT iw.branch FROM epic_tasks et "
                    "LEFT JOIN item_worktrees iw "
                    "ON iw.id = et.item_worktree_id AND iw.state = 'active' "
                    "WHERE et.epic_id = %s AND et.task_num = %s",
                    (target.epic_id, target.task_num),
                )
                if branch_row:
                    branch = branch_row["branch"]
                if not branch:
                    item_row = query_one(
                        conn,
                        "SELECT "
                        f"{primary_item_worktree_branch_sql('i.id')} AS branch "
                        "FROM items i WHERE i.id = %s",
                        (target.epic_id,),
                    )
                    if item_row:
                        branch = item_row["branch"]
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
    target: GateTarget, db_path: str, *, repo_root: Optional[str] = None
) -> LatestCodeRef:
    """Resolve the revision a browser run must have been captured against.

    A checkout answers this, because the branch itself is the truth. A
    control plane serving a customer project has none, and silently skipping
    the comparison there would accept a capture of any age, so the revisions
    this control plane records for the item answer instead.

    That substitution is deliberately confined to hosts with no checkout at
    all. Where one exists and git still cannot name a revision — an item with
    no lane, a branch that is gone — the answer stays "unknown", exactly as
    it has been; treating it as the recorded revision there would newly call
    older captures stale for a reason that has nothing to do with them.
    """
    from yoke_core.domain.qa_browser_checkout_free_proof import (
        recorded_latest_code_ref,
    )

    resolved = _git_latest_code_ref(target, db_path)
    if repo_root or resolved.sha or resolved.timestamp:
        return resolved
    return recorded_latest_code_ref(target, db_path, branch=resolved.branch)


def _git_latest_code_ref(
    target: GateTarget, db_path: str
) -> LatestCodeRef:
    """Resolve the latest branch / SHA / timestamp from the project checkout."""
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


# Staleness judgment over those resolved revisions lives in its own module;
# re-exported here because the gates and their suites import it by this path.
from yoke_core.domain.qa_browser_freshness_check import (  # noqa: E402,F401
    _browser_freshness_errors,
    _browser_run_is_fresh,
    _collect_stale_browser_requirements,
    _extract_code_identity,
    _latest_browser_run,
)
