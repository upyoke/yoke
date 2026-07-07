"""claim-work stale-window alignment regressions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from yoke_core.domain.db_helpers import connect
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import session_offer_db  # noqa: F401


def _iso(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _seed_conflict(db_path: str, tmp_dir: str, *, executor: str, minutes_ago: int) -> None:
    seen_at = _iso(minutes_ago)
    fresh_at = _iso(0)
    conn = connect(db_path)
    conn.execute(
        """INSERT INTO harness_sessions (session_id, executor, provider, model,
           execution_lane, workspace, mode, offered_at, last_heartbeat)
           VALUES ('owner-session', %s, 'anthropic', 'opus', 'primary',
           %s, 'hook', %s, %s)""",
        (executor, tmp_dir, seen_at, seen_at),
    )
    conn.execute(
        """INSERT INTO harness_sessions (session_id, executor, provider, model,
           execution_lane, workspace, mode, offered_at, last_heartbeat)
           VALUES ('thief-session', 'claude-desktop', 'anthropic', 'opus', 'primary',
           %s, 'hook', %s, %s)""",
        (tmp_dir, fresh_at, fresh_at),
    )
    conn.execute(
        """INSERT INTO work_claims (session_id, target_kind, item_id, claim_type,
           claimed_at, last_heartbeat)
           VALUES ('owner-session', 'item', '10', 'exclusive', %s, %s)""",
        (seen_at, seen_at),
    )
    conn.commit()
    conn.close()


def test_claim_work_reclaims_base_ttl_stale_claim(session_offer_db):
    db_path = session_offer_db["db_path"]
    _seed_conflict(
        db_path,
        session_offer_db["tmp_dir"],
        executor="claude-desktop",
        minutes_ago=25,
    )

    result = _run_client(
        ["claim-work", "--session-id", "thief-session", "--item", "YOK-10"],
        db_path=db_path,
    )

    assert result.returncode == 0
    conn = connect(db_path)
    released_reason = conn.execute(
        "SELECT release_reason FROM work_claims WHERE session_id='owner-session'"
    ).fetchone()[0]
    conn.close()
    assert released_reason == "reclaimed"


def test_claim_work_keeps_codex_between_turn_claim_live(session_offer_db):
    db_path = session_offer_db["db_path"]
    _seed_conflict(
        db_path,
        session_offer_db["tmp_dir"],
        executor="codex-desktop",
        minutes_ago=45,
    )

    result = _run_client(
        ["claim-work", "--session-id", "thief-session", "--item", "YOK-10"],
        db_path=db_path,
    )

    assert result.returncode == 1
    err = json.loads(result.stderr)
    assert "already claimed" in err["error"]
