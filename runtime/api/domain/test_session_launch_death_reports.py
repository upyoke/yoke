"""One relay death report settles a registered launch before acknowledgement."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from runtime.api.domain.test_session_process_liveness_report import (
    EVIDENCE, MACHINE, _apply, _ghost, conn as conn,
)
from yoke_core.domain.session_launch_store import get_launch, insert_instruction_message


@pytest.mark.parametrize("scenario", ["dead", "worked", "live"])
def test_registered_launch_is_settled_only_for_death_before_work(conn, scenario):
    session_id = _ghost(conn)
    actor_id = conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()["id"]
    launch_id, message_id = str(uuid4()), str(uuid4())
    now = datetime.now(timezone.utc)
    insert_instruction_message(
        conn, message_id=message_id, launch_id=launch_id, actor_id=actor_id,
        session_id=None, sender_surface=None, project_id=1,
        body="Inspect and report.", created_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id, requester_actor_id, project_id, requested_surface, selected_surface, message_id, "
        "state, registered_session_id, native_session_id, created_at, deadline_at) "
        "VALUES (%s, %s, 1, 'codex-cli', 'codex-cli', %s, 'awaiting_registration', "
        "%s, %s, %s, %s)",
        (launch_id, actor_id, message_id, session_id, session_id,
         now, now + timedelta(minutes=10)),
    )
    if scenario == "worked":
        conn.execute(
            "UPDATE harness_sessions SET first_completed_work_at=last_heartbeat "
            "WHERE session_id=%s", (session_id,),
        )
    conn.commit()
    before = get_launch(conn, launch_id)
    evidence = {
        **EVIDENCE, "launch_id": launch_id, "exit_code": 1,
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

    stored = get_launch(conn, launch_id)
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

