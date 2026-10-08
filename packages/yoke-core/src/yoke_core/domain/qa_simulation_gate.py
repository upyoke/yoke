"""Authorize integration simulation from each effective case's actual attempt."""

from __future__ import annotations

import os
import sys

from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_gate_definitions import GateResult
from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql
from yoke_core.domain.qa_requirement_pass_currency import has_current_passing_run
from yoke_core.domain.qa_latest_execution import latest_executions


def check_epic_simulation_gate(epic_id: int, db_path: str) -> GateResult:
    """Every effective simulation needs a completed pass or its explicit bounded triage discharge."""
    if os.environ.get("YOKE_SKIP_SIMULATION") == "1":
        from yoke_core.domain.project_identity_item_ref import item_ref_for_id

        print(
            "WARNING: Integration simulation gate bypassed via YOKE_SKIP_SIMULATION "
            f"for {item_ref_for_id(int(epic_id))}",
            file=sys.stderr,
        )
        return GateResult(passed=True)
    conn = connect(db_path)
    try:
        epic_ref = render_item_ref(conn, epic_id)
        rows = query_rows(
            conn,
            f"SELECT id, (NOT {settled_obligation_sql(conn)}) AS active "
            "FROM qa_requirements WHERE qa_kind='simulation' AND item_id=%s "
            "AND success_policy LIKE '%%integration%%' ORDER BY id",
            (epic_id,),
        )
        if not rows:
            return GateResult(
                passed=False,
                errors=[
                    f"Error: No integration simulation found for epic {epic_ref}.",
                    f"Run '/yoke simulate {epic_ref} --phase integration' before advancing.",
                ],
            )
        ids = [int(row["id"]) for row in rows if row["active"]]
        attempts = latest_executions(conn, ids)
        errors = []
        for requirement_id in ids:
            if has_current_passing_run(conn, requirement_id):
                continue
            run = attempts.get(requirement_id)
            verdict = str(run["verdict"] or "pending") if run else "missing"
            reason = str(run["verdict_reason"] or "") if run else ""
            errors.append(
                f"Error: Integration simulation for epic {epic_ref}, requirement "
                f"#{requirement_id}, is {verdict}: {reason}. Only completed pass authorizes."
            )
        return GateResult(passed=not errors, errors=errors)
    except ValueError as exc:
        return GateResult(passed=False, errors=[str(exc)])
    finally:
        conn.close()


__all__ = ["check_epic_simulation_gate"]
