"""One relay death report settles a registered launch before acknowledgement."""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.test_session_process_liveness_report import (
    EVIDENCE, MACHINE, _apply, _ghost, conn as conn,
)
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_store import get_launch
from yoke_core.domain.session_launch_types import LaunchAuthorization, LaunchRequest


@pytest.mark.parametrize("scenario", ["dead", "worked", "live"])
def test_registered_launch_is_settled_only_for_death_before_work(conn, scenario):
    session_id = _ghost(conn)
    actor_id = conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()["id"]
    launch = create_launch(
        conn,
        auth=LaunchAuthorization(
            actor_id=actor_id, session_id=None, can_operate_project=True,
        ),
        request=LaunchRequest(
            project_id=1, executor_surface="codex-cli",
            instructions="Inspect and report.", work_required=False,
        ),
    ).launch
    conn.execute(
        "UPDATE session_launches SET state='awaiting_registration', "
        "registered_session_id=%s, native_session_id=%s WHERE launch_id=%s",
        (session_id, session_id, launch.launch_id),
    )
    if scenario == "worked":
        conn.execute(
            "UPDATE harness_sessions SET first_completed_work_at=last_heartbeat "
            "WHERE session_id=%s", (session_id,),
        )
    conn.commit()
    before = get_launch(conn, launch.launch_id)
    evidence = {
        **EVIDENCE, "launch_id": launch.launch_id, "exit_code": 1,
        "native_stderr_tail": "Selected model is at capacity",
    }

    if scenario == "live":
        from yoke_core.domain.session_process_liveness_report import (
            apply_verified_process_death_reports,
        )

        result = apply_verified_process_death_reports(
            conn, machine_id=MACHINE, authorized_projects=(1,), reports=[],
        )
    else:
        result = _apply(conn, session_id, evidence=evidence)

    stored = get_launch(conn, launch.launch_id)
    if scenario != "dead":
        assert stored == before
        assert result["launches_corrected"] == []
    else:
        assert result["launches_corrected"] == [session_id]
        assert stored.state == "failed"
        assert stored.result_code == "abandoned_without_claim"
        recorded = json.loads(stored.result_evidence)
        assert recorded["launch_phase_reached"] == "awaiting_registration"
        assert recorded["exit_code"] == 1
        assert recorded["native_stderr_tail"] == "Selected model is at capacity"

