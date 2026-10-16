"""Resolve one QA source lane, keeping its branch, path and commit together."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.session_claimed_worktrees import claimed_worktrees


class SourceLaneError(ValueError):
    """The requested source cannot identify one authorized lane."""


def resolve_source_lane(
    conn: Any,
    *,
    item_id: int | None,
    task_num: int | None = None,
    session_id: str = "",
    checkout_path: str | None = None,
    expected_branch: str | None = None,
    case: dict | None = None,
) -> dict:
    if case and (
        case.get("deployment_run_id")
        or case.get("runner_id") not in {"ci_run", "worktree_run"}
    ):
        return {}
    if item_id is None:
        return {}
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = query_rows(
        conn,
        "SELECT iw.id, iw.branch, iw.path, iw.commit_sha, iw.state, iw.released_at "
        "FROM item_worktrees iw "
        f"WHERE iw.item_id={p} "
        + (
            f"AND iw.id=(SELECT item_worktree_id FROM epic_tasks WHERE epic_id={p} "
            f"AND task_num={p}) "
            if task_num is not None
            else ""
        )
        + "ORDER BY iw.id DESC",
        (item_id, item_id, task_num) if task_num is not None else (item_id,),
    )
    active = [r for r in rows if r["state"] == "active" and r["released_at"] is None]
    explicit = (
        checkout_path is not None or expected_branch is not None or task_num is not None
    )
    choices = active if active or explicit else rows[:1]
    if checkout_path:
        choices = [r for r in choices if r["path"] == checkout_path]
    if expected_branch:
        choices = [r for r in choices if r["branch"] == expected_branch]
    if not choices and not rows and not explicit:
        from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION
        from yoke_core.domain.item_json_sections import read_json_section

        evidence = read_json_section(
            conn, item_id=item_id, section=DASH_EVIDENCE_SECTION
        )
        return {"lane_commit_sha": evidence.get("commit_sha")} if evidence else {}
    if session_id and active:
        authorized = {
            lane.worktree_path
            for lane in claimed_worktrees(conn, session_id=session_id)
            if lane.item_id == item_id
        }
        choices = [r for r in choices if r["path"] in authorized]
    if len(choices) != 1:
        raise SourceLaneError(
            f"qa_source_lane_unresolved: item_id={item_id}, task_num={task_num}, "
            f"checkout={checkout_path!r}, branch={expected_branch!r}; "
            f"matched {len(choices)} authorized lanes. Recovery: hold the matching "
            "item/task claim and select its exact registered lane with "
            "--checkout-path PATH --expected-branch BRANCH --expected-sha FULL_SHA; "
            "inspect the item's registered lanes instead of choosing a sibling."
        )
    selected = choices[0]
    return {
        "lane_id": selected["id"],
        "lane_branch": selected["branch"],
        "lane_path": selected["path"],
        "lane_commit_sha": selected["commit_sha"],
    }
