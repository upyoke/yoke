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

import contextlib
import io
import json
import os
from typing import Optional

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_obligation_settlement import effective_requirement
from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run
from yoke_core.domain.epic_parsing import (
    _placeholder,
    _require_task_exists,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.simulation_report_headers import (
    SimulationReceipt,
    parse_simulation_headers,
)
from yoke_core.domain.simulation_attempt_read import verify_simulation_attempt
from yoke_core.domain.qa_workflow_binding_validation import (
    item_transition_for_gate,
)
from yoke_core.domain.workflow_gate_catalog import (
    GATE_PLAN_SIMULATION,
    GATE_QA_VERIFICATION,
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

    candidates = query_rows(
        conn,
        f"SELECT id FROM qa_requirements WHERE epic_id={_placeholder(conn)} "
        f"AND task_num={_placeholder(conn)} "
        "AND qa_kind='implementation_review' AND qa_phase='verification'",
        (str(epic_id), task_num),
    )
    effective = {
        int(row["id"]): row
        for candidate in candidates
        for row in [effective_requirement(conn, int(candidate["id"]))]
    }
    if effective:

        def priority(row):
            blocking = row["blocking_mode"] == "blocking"
            discharged = bool(row["waived_at"] or row.get("retracted_at"))
            return (
                discharged,
                not blocking,
                has_current_passing_run(conn, int(row["id"]))
                if not discharged
                else False,
                int(row["id"]),
            )

        return int(min(effective.values(), key=priority)["id"])

    workflow_transition_id = item_transition_for_gate(
        conn,
        item_id=int(epic_id),
        gate_id=GATE_QA_VERIFICATION,
    )
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
            workflow_transition_id=workflow_transition_id,
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

    return _epic_mod._ensure_implementation_review_requirement(
        conn, epic_id, task_num, scripts_dir=scripts_dir
    )


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
) -> SimulationReceipt:
    """Retain and verify one simulation attempt after validating its public identity."""
    public_ref = render_item_ref(conn, int(epic_id))
    result = parse_simulation_headers(body, public_ref)
    verdict = {"CLEAN": "pass", "GAPS FOUND": "fail"}[result]
    verdict_reason = None

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
    else:
        req_id = None

    if req_id is None:
        gate_id = GATE_PLAN_SIMULATION if phase == "plan" else GATE_QA_VERIFICATION
        workflow_transition_id = item_transition_for_gate(
            conn,
            item_id=int(epic_id),
            gate_id=gate_id,
        )
        diagnostic = io.StringIO()
        try:
            with contextlib.redirect_stderr(diagnostic):
                req_id = _qa_req_add(
                    item_id=int(epic_id),
                    qa_kind="simulation",
                    qa_phase="verification",
                    target_env=None,
                    blocking_mode="blocking",
                    requirement_source="explicit",
                    success_policy=success_policy,
                    workflow_transition_id=workflow_transition_id,
                )
        except SystemExit as exc:
            raise RuntimeError(
                "simulation_requirement_create_failed: "
                f"{diagnostic.getvalue().strip() or f'QA requirement creation exited {exc.code}'}. "
                "Inspect the named refusal and simulation-get before retrying."
            ) from exc

    try:
        run_id = _qa_run_add(
            requirement_id=int(req_id),
            performed_by="agent",
            qa_kind="simulation",
            verdict=verdict,
            verdict_reason=verdict_reason,
            raw_result=raw_result,
        )
    except SystemExit as exc:
        raise RuntimeError(
            f"Error creating run: qa run-add exited with {exc.code}"
        ) from exc

    receipt = SimulationReceipt(public_ref, phase, int(req_id), int(run_id), result)
    verify_simulation_attempt(conn, int(epic_id), receipt)
    return receipt
