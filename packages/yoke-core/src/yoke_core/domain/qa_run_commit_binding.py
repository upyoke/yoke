"""Bind a hand-recorded QA run to the commit it verified.

A passing blocking verdict without ``verification_tree.head_sha`` reads as
satisfied at write time and then refuses at merge. This module stamps the
claimed lane HEAD (or an explicit override), keeps ``raw_result`` as
evidence text, and refuses with a named reason when no sha can be bound.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Callable, Optional

from yoke_core.domain.qa_merging_identity import recorded_head_sha
from yoke_core.domain.schema_common import _column_exists, _table_exists


HAND_ACTORS = frozenset({"agent", "human"})
REQUIRED_SHAPE = (
    'a passing verdict on a blocking requirement must name the tree it '
    'verified: pass --head-sha <commit>, or record on a clean claimed lane '
    'so the write stamps {"verification_tree": {"head_sha": "<commit>"}}. '
    "--raw-result stays evidence text, not the run identity."
)
NO_LANE = "no_lane: no claimed lane resolved. " + REQUIRED_SHAPE
DIRTY_TREE = (
    "dirty_tree: claimed lane working tree is dirty; commit or stash, "
    "or pass --head-sha. " + REQUIRED_SHAPE
)
MISSING_HEAD_SHA = "missing_head_sha: " + REQUIRED_SHAPE

ResolveLane = Callable[[], tuple[str, str, str]]


def needs_commit_binding(
    verdict: Optional[str], blocking_mode: Optional[str], waived_at: Any,
) -> bool:
    if str(verdict or "").strip().lower() != "pass":
        return False
    if str(blocking_mode or "") != "blocking":
        return False
    return not waived_at


def should_bind_raw_result(
    *,
    verdict: Optional[str],
    blocking_mode: Optional[str],
    waived_at: Any,
    performed_by: str,
    raw_result: Optional[str],
    head_sha: Optional[str],
) -> bool:
    if not needs_commit_binding(verdict, blocking_mode, waived_at):
        return False
    if str(head_sha or "").strip() or recorded_head_sha(raw_result):
        return True
    if str(performed_by or "") in HAND_ACTORS:
        return True
    return bool(str(raw_result or "").strip()) and not recorded_head_sha(raw_result)


def wrap_evidence(raw_result: Optional[str], head_sha: str, root: str = "") -> str:
    """Keep prose as evidence and put the sha in verification_tree."""
    payload: dict[str, Any]
    try:
        loaded = json.loads(str(raw_result or ""))
    except (TypeError, ValueError):
        loaded = None
    if isinstance(loaded, dict):
        payload = dict(loaded)
    else:
        payload = {}
        evidence = str(raw_result or "").strip()
        if evidence:
            payload["evidence"] = evidence
    tree = payload.get("verification_tree")
    tree = dict(tree) if isinstance(tree, dict) else {}
    tree["head_sha"] = head_sha
    if root:
        tree.setdefault("root", root)
    payload["verification_tree"] = tree
    return json.dumps(payload, sort_keys=True)


def _git(root: str, *args: str) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def resolve_item_lane(conn: Any, item_id: Any) -> tuple[str, str, str]:
    """Return ``(root, head_sha, error_reason)`` for the item's active lane."""
    if conn is None or item_id is None:
        return "", "", "no_lane"
    if not (
        _table_exists(conn, "item_worktrees")
        and _column_exists(conn, "item_worktrees", "path")
    ):
        return "", "", "no_lane"
    from yoke_core.domain import db_backend

    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT path, commit_sha FROM item_worktrees "
        f"WHERE item_id = {placeholder} AND state = 'active' "
        "ORDER BY id DESC LIMIT 1",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return "", "", "no_lane"
    root = str(row["path"] if hasattr(row, "keys") else row[0] or "").strip()
    recorded = str(row["commit_sha"] if hasattr(row, "keys") else row[1] or "").strip()
    if root and os.path.isdir(root):
        if _git(root, "status", "--porcelain"):
            return root, "", "dirty_tree"
        head = _git(root, "rev-parse", "HEAD")
        if head:
            return root, head, ""
        return root, "", "no_lane"
    if recorded:
        return root, recorded, ""
    return root, "", "no_lane"


def bind_recorded_raw_result(
    *,
    verdict: Optional[str],
    raw_result: Optional[str],
    performed_by: str,
    blocking_mode: Optional[str],
    waived_at: Any = None,
    head_sha: Optional[str] = None,
    item_id: Any = None,
    conn: Any = None,
    resolve_lane: Optional[ResolveLane] = None,
) -> tuple[Optional[str], str]:
    """Return ``(bound_raw_result, error)``. ``error`` is empty on success."""
    if not should_bind_raw_result(
        verdict=verdict,
        blocking_mode=blocking_mode,
        waived_at=waived_at,
        performed_by=performed_by,
        raw_result=raw_result,
        head_sha=head_sha,
    ):
        return raw_result, ""
    existing = recorded_head_sha(raw_result)
    override = str(head_sha or "").strip()
    root = ""
    sha = override or existing
    if not sha:
        resolver = resolve_lane or (lambda: resolve_item_lane(conn, item_id))
        root, sha, reason = resolver()
        if reason == "dirty_tree":
            return raw_result, DIRTY_TREE
        if reason == "no_lane" or not sha:
            return raw_result, NO_LANE
    if not sha:
        return raw_result, MISSING_HEAD_SHA
    return wrap_evidence(raw_result, sha, root=root), ""


def bind_cli_raw_result(
    *,
    verdict: Optional[str],
    raw_result: Optional[str],
    performed_by: str,
    requirement_id: int,
    db_path: Optional[str] = None,
    head_sha: Optional[str] = None,
) -> Optional[str]:
    """CLI adapter: bind or ``sys.exit(2)`` with the named refusal."""
    from yoke_core.domain.db_helpers import connect, query_one

    conn = connect(path=db_path)
    try:
        row = query_one(
            conn,
            "SELECT blocking_mode, waived_at, item_id FROM qa_requirements "
            "WHERE id = %s",
            (int(requirement_id),),
        )
        if row is None:
            print(
                f"Error: requirement_id {requirement_id} not found in qa_requirements",
                file=sys.stderr,
            )
            sys.exit(2)
        bound, error = bind_recorded_raw_result(
            verdict=verdict,
            raw_result=raw_result,
            performed_by=performed_by,
            blocking_mode=row["blocking_mode"],
            waived_at=row["waived_at"],
            head_sha=head_sha,
            item_id=row["item_id"],
            conn=conn,
        )
    finally:
        conn.close()
    if error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(2)
    return bound


__all__ = [
    "DIRTY_TREE",
    "HAND_ACTORS",
    "MISSING_HEAD_SHA",
    "NO_LANE",
    "REQUIRED_SHAPE",
    "bind_cli_raw_result",
    "bind_recorded_raw_result",
    "needs_commit_binding",
    "resolve_item_lane",
    "should_bind_raw_result",
    "wrap_evidence",
]
