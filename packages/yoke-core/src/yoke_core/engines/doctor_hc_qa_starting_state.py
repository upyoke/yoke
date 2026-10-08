"""Doctor HC: every stored plan with a machine-run case can materialize.

A machine-run case (``host_control`` or ``agent_mission`` method) declares
the Test Machine state it starts from, and materialization refuses a plan
whose cases cannot say where they start. Authoring enforces that contract on
every new write, but a stored plan written before the contract existed, or
before it was last tightened, only fails when its QA runs. This check reads
every live plan through the same :func:`plan_cases` derivation the writers
use, so tightening the contract without converging the stored plans fails
here instead of at a deployment's QA gate.
"""

from __future__ import annotations

from typing import List

from yoke_contracts.qa_case_starting_state import MACHINE_RUNNER_IDS
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_plan_case_definition import plan_cases
from yoke_core.domain.qa_plan_management import QaPlanError

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-qa-plan-machine-starting-state"
_HC_DESC = "Stored QA plans whose machine-run cases cannot materialize"


def hc_qa_plan_starting_state(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    if not _base._table_exists(conn, "qa_plan_cases"):
        rec.record(
            _HC_NAME, _HC_DESC, "PASS", "qa_plan_cases table missing -- skipping"
        )
        return
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    runners = sorted(MACHINE_RUNNER_IDS)
    plans = query_rows(
        conn,
        "SELECT p.id, p.slug, pr.slug AS project FROM qa_plans p "
        "JOIN projects pr ON pr.id = p.project_id "
        "WHERE p.retired_at IS NULL AND EXISTS ("
        "SELECT 1 FROM qa_plan_cases c JOIN qa_methods m ON m.id = c.method_id "
        f"WHERE c.plan_id = p.id AND m.runner_id IN ({', '.join(marker for _ in runners)})"
        ") ORDER BY pr.slug, p.slug",
        tuple(runners),
    )
    fails: List[str] = []
    for plan in plans:
        try:
            plan_cases(conn, int(plan["id"]))
        except QaPlanError as exc:
            fails.append(f"- {plan['project']} plan {plan['id']}: {exc}")
    if fails:
        rec.record(_HC_NAME, _HC_DESC, "FAIL", "\n".join(fails))
    else:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")


__all__ = ["hc_qa_plan_starting_state"]
