"""Controller-only mission capture through the existing ordered-case protocol."""

from yoke_core.domain.db_savepoint import savepoint
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
from yoke_core.domain.agent_mission_docket import insert_mission_docket
from yoke_core.domain.qa_plan_execution_state import advance_plan_execution
from yoke_core.domain.qa_plan_execution_store import result_rows


def record_controller_mission(conn, execution, case, *, ordinal):
    """Record one replayable docket without acquiring or changing any host lease."""
    with savepoint(conn):
        for row in result_rows(conn, str(execution["id"])):
            if row["ordinal"] == ordinal:
                return dict(row["result"])
        _, result = insert_mission_docket(
            conn,
            execution=execution,
            case=case,
            preparation={"ok": True, "evidence": {"location": "controller"}},
            lease_id=None,
            contract_digest="",
        )
        advance_plan_execution(
            conn,
            execution,
            ordinal=ordinal,
            requirement_id=int(case["requirement_id"]),
            result=result,
            commit=False,
        )
        return result


def execute_controller_mission(case, *, execution_id, ordinal, actor, target, call):
    """Ask the authoritative server to capture a hostless mission's docket."""
    begun = call(
        function_id="test_machine.plan_case.begin",
        target=target,
        actor=actor,
        payload={
            "execution_id": execution_id,
            "ordinal": ordinal,
            "requirement_id": int(case["requirement_id"]),
        },
    )
    result = begun.get("result")
    if begun.get("state") != "retained" or not isinstance(result, dict):
        raise QaPlanExecutionError(
            "controller_mission_capture_unavailable: the server returned no controller "
            "docket; have the control-plane operator verify the serving release "
            "supports controller missions before retrying this execution"
        )
    return dict(result)
