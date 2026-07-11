"""Terminal workflow-dispatch intent retention safety."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from yoke_core.domain.github_workflow_dispatch_intents import (
    INTENT_TTL_DAYS,
    claim_attempt,
    count_expired,
    prune_expired,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _claim(request_id: str) -> None:
    assert claim_attempt(
        request_id=request_id,
        attempt=1,
        actor_id="2",
        authorization_scope="project:1",
        payload_checksum=f"checksum-{request_id}",
        repo="upyoke/platform",
        workflow="deploy.yml",
        workflow_ref="main",
        inputs={},
        correlation_id=f"correlation-{request_id}",
    )


def test_prune_expires_only_terminal_intents_and_never_pending(
    tmp_path: Path,
) -> None:
    old = (
        datetime.now(timezone.utc) - timedelta(days=INTENT_TTL_DAYS + 1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    with init_test_db(tmp_path) as db_path:
        for request_id in ("completed-old", "rejected-old", "pending-old", "recent"):
            _claim(request_id)
        with connect_test_db(db_path) as conn:
            conn.execute(
                "UPDATE github_workflow_dispatch_intents SET state='completed', "
                "workflow_run_id='1', updated_at=%s WHERE request_id='completed-old'",
                (old,),
            )
            conn.execute(
                "UPDATE github_workflow_dispatch_intents SET state='rejected', "
                "updated_at=%s WHERE request_id='rejected-old'",
                (old,),
            )
            conn.execute(
                "UPDATE github_workflow_dispatch_intents SET updated_at=%s "
                "WHERE request_id='pending-old'",
                (old,),
            )
            conn.execute(
                "UPDATE github_workflow_dispatch_intents SET state='completed', "
                "workflow_run_id='2' WHERE request_id='recent'"
            )
            conn.commit()
            assert count_expired(conn) == 2
            assert prune_expired(conn) == 2
            conn.commit()
            rows = conn.execute(
                "SELECT request_id, state FROM github_workflow_dispatch_intents "
                "ORDER BY request_id"
            ).fetchall()

    assert rows == [("pending-old", "pending"), ("recent", "completed")]
