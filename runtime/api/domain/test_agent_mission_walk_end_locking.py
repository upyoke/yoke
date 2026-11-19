"""Walk-end stores its restore receipt under the execution lock it already holds.

Each ``connect()`` here opens its own real PostgreSQL connection, so a second
writer that re-locks the walking execution would wait on walk-end's own lock.
"""

from time import monotonic

import pytest

from runtime.api.domain import (
    agent_mission_cleanup_test_support as cleanup_support,
)
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_core.domain.agent_mission_recording import handle_agent_mission_access
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.machine_reset_debt import reset_owed
from yoke_core.domain.qa_plan_execution_store import select_plan_execution

removed_mission = cleanup_support.removed_mission


@pytest.mark.parametrize("removed_mission", ["removed", "failed"], indirect=True)
def test_walk_end_records_proven_restore_on_its_own_locked_connection(
    test_db, removed_mission, monkeypatch
):
    request, _, original = removed_mission
    acquired = handle_agent_mission_access(request)
    assert acquired.primary_success, acquired.error
    test_db.commit()
    opened = []

    def real_connect(*_args, **_kwargs):
        opened.append(connect_test_database(test_db.info.dbname))
        return opened[-1]

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", real_connect)
    started = monotonic()
    try:
        finished = handle_agent_mission_access(
            request.model_copy(
                update={
                    "payload": {
                        **request.payload,
                        "cleanup": "finish",
                        "lease_id": original["lease_id"],
                        "restore": {"restored": True, "baseline": "fresh-host"},
                    }
                }
            )
        )
        elapsed = monotonic() - started
    finally:
        for conn in opened:
            conn.close()
    assert opened, "walk-end must run on real connections"
    assert finished.primary_success, finished.error
    assert elapsed < 2
    run_id = request.payload["run_id"]
    assert test_db.execute(
        "SELECT count(*) FROM qa_artifacts WHERE qa_run_id=%s "
        "AND artifact_type='starting_state_restore'",
        (run_id,),
    ).fetchone()[0] == 1
    assert reset_owed(test_db, original["settings"]["resource_name"]) is None
    assert not get_claim(test_db, original["lease_id"]).is_active
    execution = select_plan_execution(
        test_db, request.payload["execution_id"], lock=False
    )
    assert execution["state"] == "aborted"
    assert execution["test_machine_lease_id"] is None
