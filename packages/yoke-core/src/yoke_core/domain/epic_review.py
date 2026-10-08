"""Review orchestration, progress notes, and proceed triage handoff.

Split from ``yoke_core.domain.epic`` to keep that file under the
800-line target.  All public names remain callable on the ``epic`` module object
via lazy wrapper re-exports so that existing callers (``epic_cli.py``) and
``mock.patch("yoke_core.domain.epic.X")`` tests are unaffected.

QA-bridge helpers (``_qa_req_add``, ``_qa_run_add``, ``_epic_connect``,
``_ensure_implementation_review_requirement``, ``_auto_transition_review_task``,
``_ensure_review_req``) and the simulation write helper (``simulation_upsert``)
live in the sibling module ``yoke_core.domain.epic_review_qa`` and are
re-exported here so existing patch targets such as
``mock.patch("yoke_core.domain.epic_review.simulation_upsert")`` continue to
resolve.

``_qa_requirement_add_silent`` and ``_qa_run_add_silent`` stay in ``epic.py``
so that patches on ``yoke_core.domain.epic._qa_requirement_add_silent`` /
``…_qa_run_add_silent`` intercept the calls made by the functions here.  Those
helpers are reached via a lazy module-attribute lookup pattern (analogous to the
``_etsg.*`` pattern used in ``epic_task_sync_github_core``).
"""

from __future__ import annotations

import json
import os
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import query_one, query_scalar
from yoke_core.domain.epic_parsing import _now_iso, _placeholder
from yoke_core.domain.epic_review_qa import (
    _auto_transition_review_task,
    _ensure_implementation_review_requirement,
    _ensure_review_req,
    _epic_connect,
    _qa_req_add,
    _qa_run_add,
    simulation_upsert,
)

__all__ = [
    "_auto_transition_review_task",
    "_ensure_implementation_review_requirement",
    "_ensure_review_req",
    "_epic_connect",
    "_qa_req_add",
    "_qa_run_add",
    "progress_note_insert",
    "progress_note_mark_synced",
    "proceed_triage_and_handoff",
    "review_insert",
    "review_seed",
    "simulation_upsert",
]


# ---------------------------------------------------------------------------
# Review orchestration
# ---------------------------------------------------------------------------


def review_seed(
    conn,
    epic_id: str,
    task_num: int,
    *,
    scripts_dir: Optional[str] = None,
) -> str:
    """Seed a blocking review requirement and auto-advance task.

    After successfully seeding the requirement, auto-advances the task from
    ``implementing`` to ``reviewing-implementation`` if the task is currently
    in that state. No-ops cleanly when the task is already past that point.
    """
    req_id = _ensure_review_req(conn, epic_id, task_num, scripts_dir=scripts_dir)

    # T-3: Auto-advance task implementing -> reviewing-implementation
    task_row = query_one(
        conn,
        f"SELECT status FROM epic_tasks WHERE epic_id={_placeholder(conn)} AND task_num={_placeholder(conn)}",
        (str(epic_id), str(task_num)),
    )
    if task_row and task_row["status"] == "implementing":
        _auto_transition_review_task(
            conn,
            epic_id,
            task_num,
            target_status="reviewing-implementation",
            source="auto-transition:review-seed",
            note="Auto-advanced by review_seed",
        )

    return f"Implementation-review requirement seeded: {epic_id}/{task_num} req_id={req_id}"


def review_insert(
    conn,
    epic_id: str,
    task_num: int,
    verdict: str,
    body: str,
    *,
    scripts_dir: Optional[str] = None,
) -> str:
    """Insert a review verdict."""
    # Map PASS/FAIL to lowercase
    lower_verdict = {"PASS": "pass", "FAIL": "fail"}.get(verdict, verdict)

    # Build raw_result JSON
    raw_result = json.dumps({"body": body})

    req_id = _ensure_review_req(conn, epic_id, task_num, scripts_dir=scripts_dir)

    env = dict(__import__("os").environ)
    env["YOKE_INTERNAL_EPIC_REVIEW_WRITE"] = "1"
    original_env = os.environ.copy()
    os.environ.update(env)
    try:
        _qa_run_add(
            requirement_id=req_id,
            performed_by="agent",
            qa_kind="implementation_review",
            verdict=lower_verdict,
            raw_result=raw_result,
        )
    except SystemExit as exc:
        raise RuntimeError(
            f"Error creating review run: qa run-add exited with {exc.code}"
        ) from exc
    finally:
        os.environ.clear()
        os.environ.update(original_env)

    # T-2: Auto-advance task reviewing-implementation -> reviewed-implementation
    # on passing review
    if lower_verdict == "pass":
        task_row = query_one(
            conn,
            f"SELECT status FROM epic_tasks WHERE epic_id={_placeholder(conn)} AND task_num={_placeholder(conn)}",
            (str(epic_id), str(task_num)),
        )
        if task_row and task_row["status"] == "reviewing-implementation":
            _auto_transition_review_task(
                conn,
                epic_id,
                task_num,
                target_status="reviewed-implementation",
                source="auto-transition:review-insert",
                note="Auto-advanced by review_insert",
            )

    return f"Inserted review: {epic_id}/{task_num} verdict={verdict}"


# ---------------------------------------------------------------------------
# Mutations: progress notes
# ---------------------------------------------------------------------------


def progress_note_insert(
    conn,
    epic_id: str,
    task_num: int,
    note_num: int,
    body: str,
    commit_hash: str = "",
) -> str:
    """Insert a progress note."""
    ts = _now_iso()
    p = _placeholder(conn)
    conn.execute(
        f"""INSERT INTO epic_progress_notes
           (epic_id, task_num, note_num, body, commit_hash, created_at)
           VALUES ({p}, {p}, {p}, {p}, {p}, {p})
           ON CONFLICT(epic_id, task_num, note_num) DO UPDATE SET
             body=excluded.body,
             commit_hash=excluded.commit_hash""",
        (str(epic_id), task_num, note_num, body, commit_hash or None, ts),
    )
    from yoke_core.domain.claim_chain_state import touch_epic_task_activity
    from yoke_core.domain.item_activity import touch_item_activity

    touch_item_activity(conn, item_id=epic_id)
    touch_epic_task_activity(conn, epic_id=epic_id, task_num=task_num, at=ts)
    conn.commit()
    return f"Inserted progress note: {epic_id}/{task_num} note {note_num}"


def progress_note_mark_synced(
    conn,
    epic_id: str,
    task_num: int,
    note_num: int,
) -> str:
    """Mark a progress note as synced."""
    p = _placeholder(conn)
    conn.execute(
        f"UPDATE epic_progress_notes SET synced_to_github=1 WHERE epic_id={p} AND task_num={p} AND note_num={p}",
        (str(epic_id), task_num, note_num),
    )
    conn.commit()
    return f"Marked progress note {epic_id}/{task_num}/{note_num} as synced"


# ---------------------------------------------------------------------------
# Proceed triage handoff
# ---------------------------------------------------------------------------


def proceed_triage_and_handoff(
    epic_id: int,
    *,
    recommendation: str,
    gap_summary: str = "",
    filed_item_ids: Optional[List[str]] = None,
    session_id: Optional[str] = None,
) -> int:
    """Record a bounded simulation discharge and hand off without inventing pass."""
    with _epic_connect() as conn:
        parent_status = query_scalar(
            conn,
            f"SELECT status FROM items WHERE id = {_placeholder(conn)}",
            (epic_id,),
        )
    if parent_status == "reviewed-implementation":
        print(
            "PROCEED triage already handed off for epic %d; "
            "parent already at reviewed-implementation." % epic_id
        )
        return 0
    if parent_status != "reviewing-implementation":
        print(
            "Error: epic %d parent status is '%s'; expected "
            "'reviewing-implementation' before PROCEED triage."
            % (epic_id, parent_status or "<not found>"),
            file=sys.stderr,
        )
        return 1

    from yoke_core.domain.qa_simulation_triage import record_simulation_triage

    try:
        with _epic_connect() as conn:
            record_simulation_triage(
                conn,
                epic_id,
                recommendation=recommendation,
                rationale=gap_summary,
                filed_public_refs=filed_item_ids or [],
                session_id=session_id,
            )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    items_str = ", ".join(filed_item_ids or []) or "none"

    # Step 2: Invoke the canonical reviewed-handoff (status write + claim release).
    from yoke_core.domain.conduct_reviewed_handoff import run as _handoff_run

    handoff_rc = _handoff_run(epic_id, session_id=session_id)
    if handoff_rc != 0:
        print(
            "Error: conduct_reviewed_handoff failed for epic %d after "
            "PROCEED triage (exit %d)." % (epic_id, handoff_rc),
            file=sys.stderr,
        )
        return 2

    print(
        "PROCEED triage accepted for epic %d: recommendation=%s, "
        "filed_items=[%s] -> reviewed-implementation (verified)"
        % (epic_id, recommendation, items_str)
    )
    return 0
