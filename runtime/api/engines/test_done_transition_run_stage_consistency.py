"""Done transition refuses a succeeded run carrying an inconsistent stage."""

from yoke_core.engines import done_transition
from runtime.api.engines._done_transition_test_helpers import connect_dt_db


class TestRunStageConsistency:
    """TC-stage-consistency: run stage consistency check."""

    def test_failed_stage_blocks(self, dt_db):
        db_path, _ = dt_db
        conn = connect_dt_db(db_path)
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, current_stage, created_at) "
            "VALUES ('r3', 1, 'succeeded', 'deploy-failed', '2025-01-01')"
        )
        conn.commit()
        conn.close()

        assert done_transition._check_run_stage_consistency("r3") is True

    def test_normal_stage_passes(self, dt_db):
        db_path, _ = dt_db
        conn = connect_dt_db(db_path)
        conn.execute(
            "INSERT INTO deployment_runs (id, project_id, status, current_stage, created_at) "
            "VALUES ('r4', 1, 'succeeded', 'deploy', '2025-01-01')"
        )
        conn.commit()
        conn.close()

        assert done_transition._check_run_stage_consistency("r4") is False
