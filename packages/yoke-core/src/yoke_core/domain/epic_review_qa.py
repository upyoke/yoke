"""QA-bridge helpers and simulation write helper for epic review flow.

Owns the indirection layer that lets test patches on
``yoke_core.domain.epic._qa_requirement_add_silent`` and friends intercept
calls made from review/progress/simulation paths.

The parent-module attribute lookup pattern
(``import yoke_core.domain.epic as _epic_mod; return _epic_mod._qa_requirement_add_silent(**kwargs)``)
is preserved verbatim so existing ``mock.patch("yoke_core.domain.epic.X")``
test fixtures continue to intercept calls regardless of which sibling module
hosts the calling function.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from yoke_core.domain.db_helpers import query_one, query_scalar
from yoke_core.domain.epic_parsing import (
    _parse_simulation_result,
    _placeholder,
    _require_task_exists,
)


def _qa_req_add(**kwargs) -> int:
    """Call _qa_requirement_add_silent via the parent module so patches intercept."""
    import yoke_core.domain.epic as _epic_mod
    return _epic_mod._qa_requirement_add_silent(**kwargs)


def _qa_run_add(**kwargs) -> int:
    """Call _qa_run_add_silent via the parent module so patches intercept."""
    import yoke_core.domain.epic as _epic_mod
    return _epic_mod._qa_run_add_silent(**kwargs)


def _epic_connect():
    """Call connect() via the parent module so patches on epic.connect intercept."""
    import yoke_core.domain.epic as _epic_mod
    return _epic_mod.connect()


# ---------------------------------------------------------------------------
# Review requirement helpers
# ---------------------------------------------------------------------------

def _ensure_implementation_review_requirement(
    conn,
    epic_id: str,
    task_num: int,
    *,
    scripts_dir: Optional[str] = None,
) -> int:
    """Find or create the canonical implementation-review requirement for an epic task.

    Idempotent: returns existing requirement ID or creates one.
    """
    _require_task_exists(conn, epic_id, task_num)

    # Prefer the live blocking requirement that still needs satisfaction
    existing = query_scalar(
        conn,
        f"""SELECT q.id
           FROM qa_requirements q
           WHERE q.epic_id={_placeholder(conn)} AND q.task_num={_placeholder(conn)}
             AND q.qa_kind='implementation_review' AND q.qa_phase='verification'
           ORDER BY
             CASE
               WHEN q.waived_at IS NULL
                 AND q.blocking_mode='blocking'
                 AND NOT EXISTS (
                   SELECT 1 FROM qa_runs qr
                   WHERE qr.qa_requirement_id = q.id AND qr.verdict='pass'
                 ) THEN 0
               WHEN q.waived_at IS NULL AND q.blocking_mode='blocking' THEN 1
               WHEN q.waived_at IS NULL THEN 2
               ELSE 3
             END,
             q.id ASC
           LIMIT 1""",
        (str(epic_id), task_num),
    )

    if existing and existing != 0:
        return int(existing)

    try:
        return _qa_req_add(
            epic_id=int(epic_id),
            task_num=task_num,
            qa_kind="implementation_review",
            qa_phase="verification",
            target_env="local",
            blocking_mode="blocking",
            requirement_source="explicit",
            success_policy='{"type":"deterministic","criteria":"verdict_pass"}',
        )
    except SystemExit as exc:
        raise RuntimeError(
            f"Error creating requirement: qa requirement-add exited with {exc.code}"
        ) from exc


def _auto_transition_review_task(
    conn,
    epic_id: str,
    task_num: int,
    *,
    target_status: str,
    source: str,
    note: str,
) -> None:
    """Apply a deterministic review-lane task transition and fail loud on errors."""
    from yoke_core.domain.update_status import update_task_status
    import io as _io

    _out = _io.StringIO()
    _err = _io.StringIO()
    _prev_source = os.environ.get("YOKE_STATUS_SOURCE")
    _prev_bypass = os.environ.get("YOKE_CLAIM_BYPASS")
    os.environ["YOKE_STATUS_SOURCE"] = source
    os.environ["YOKE_CLAIM_BYPASS"] = f"{source}:{epic_id}/{task_num}"
    try:
        rc = update_task_status(
            conn,
            str(epic_id),
            str(task_num),
            target_status,
            note=note,
            no_rebuild=True,
            stdout=_out,
            stderr=_err,
        )
    finally:
        if _prev_source is None:
            os.environ.pop("YOKE_STATUS_SOURCE", None)
        else:
            os.environ["YOKE_STATUS_SOURCE"] = _prev_source
        if _prev_bypass is None:
            os.environ.pop("YOKE_CLAIM_BYPASS", None)
        else:
            os.environ["YOKE_CLAIM_BYPASS"] = _prev_bypass

    if rc != 0:
        detail = _err.getvalue().strip() or _out.getvalue().strip() or f"exit {rc}"
        raise RuntimeError(
            f"Auto-transition failed for {epic_id}/{task_num} -> {target_status}: {detail}"
        )


def _ensure_review_req(conn, epic_id, task_num, *, scripts_dir=None) -> int:
    """Call _ensure_implementation_review_requirement via the parent module so patches intercept."""
    import yoke_core.domain.epic as _epic_mod
    return _epic_mod._ensure_implementation_review_requirement(conn, epic_id, task_num, scripts_dir=scripts_dir)


# ---------------------------------------------------------------------------
# Simulation upsert
# ---------------------------------------------------------------------------

def simulation_upsert(
    conn,
    epic_id: str,
    phase: str,
    body: str,
    *,
    scripts_dir: Optional[str] = None,
) -> str:
    """Upsert a simulation report.

    Parses result (CLEAN/GAPS FOUND) from body text.
    Writes to qa_requirements + qa_runs.
    """
    result = _parse_simulation_result(body)

    # Map result to qa_runs verdict
    verdict = "inconclusive"
    if result == "CLEAN":
        verdict = "pass"
    elif result == "GAPS FOUND":
        verdict = "fail"

    raw_result = json.dumps({"body": body, "phase": phase}, separators=(",", ":"))
    success_policy = json.dumps(
        {"type": "deterministic", "criteria": "result_pass", "phase": phase},
        separators=(",", ":"),
    )

    # Check for existing requirement
    # deliberate case-sensitive match against internal JSON-literal phase token
    row = query_one(
        conn,
        (
            "SELECT id FROM qa_requirements WHERE qa_kind='simulation' "
            f"AND item_id={_placeholder(conn)} AND success_policy LIKE {_placeholder(conn)}"
        ),
        (str(epic_id), f'%"phase":"{phase}"%'),
    )

    if row:
        req_id = row["id"]
        conn.execute(
            f"DELETE FROM qa_runs WHERE qa_requirement_id={_placeholder(conn)}",
            (req_id,),
        )
        conn.commit()
    else:
        req_id = None

    if req_id is None:
        try:
            req_id = _qa_req_add(
                item_id=int(epic_id),
                qa_kind="simulation",
                qa_phase="verification",
                target_env="local",
                blocking_mode="blocking",
                requirement_source="explicit",
                success_policy=success_policy,
            )
        except SystemExit as exc:
            raise RuntimeError(
                f"Error creating requirement: qa requirement-add exited with {exc.code}"
            ) from exc

    try:
        _qa_run_add(
            requirement_id=int(req_id),
            executor_type="agent",
            qa_kind="simulation",
            verdict=verdict,
            raw_result=raw_result,
        )
    except SystemExit as exc:
        raise RuntimeError(
            f"Error creating run: qa run-add exited with {exc.code}"
        ) from exc

    return f"Upserted simulation: {epic_id}/{phase}"
