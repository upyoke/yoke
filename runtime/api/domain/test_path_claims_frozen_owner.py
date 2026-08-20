"""Frozen item-owned path claims are dormant until thaw revalidates them."""

# ruff: noqa: F811

from __future__ import annotations

from typing import Any

from runtime.api.domain._path_claims_test_helpers import (
    SNAP,
    conn,  # noqa: F401
    local_human,
    register_test_claim as register,
    seed_item,
    seed_target,
)
from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import backlog_update_op
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.items_flags import handle_thaw
from yoke_core.domain.path_claims import activate
from yoke_core.domain.path_claims_overlap import (
    OverlapClassification,
    classify_overlap,
)
from yoke_core.domain.path_claims_thaw import (
    THAW_OVERLAP_BLOCKED_REASON,
    revalidate_item_path_claims_on_thaw,
)


SESSION = "frozen-owner-thaw-session"


def _freeze(conn: Any, item_id: int) -> None:
    conn.execute("UPDATE items SET frozen = 1 WHERE id = %s", (item_id,))
    conn.commit()


def test_classify_overlap_skips_frozen_active_owner(conn):
    actor = local_human(conn)
    frozen_item = seed_item(conn, item_id=40)
    live_item = seed_item(conn, item_id=41)
    target = seed_target(conn, path_string="src/frozen_active.py")
    frozen_claim = register(
        conn,
        actor_id=actor,
        item_id=frozen_item,
        integration_target="main",
        target_ids=[target],
    )
    activate(conn, claim_id=frozen_claim, base_commit_sha=SNAP)
    _freeze(conn, frozen_item)

    result = classify_overlap(
        conn,
        target_ids=[target],
        integration_target="main",
        candidate_item_id=live_item,
    )
    assert result is OverlapClassification.NONE

    live_claim = register(
        conn,
        actor_id=actor,
        item_id=live_item,
        integration_target="main",
        target_ids=[target],
    )
    activate(conn, claim_id=live_claim, base_commit_sha=SNAP)
    assert live_claim != frozen_claim


def test_classify_overlap_still_blocks_unfrozen_active_owner(conn):
    actor = local_human(conn)
    holder = seed_item(conn, item_id=42)
    target = seed_target(conn, path_string="src/live_active.py")
    claim = register(
        conn,
        actor_id=actor,
        item_id=holder,
        integration_target="main",
        target_ids=[target],
    )
    activate(conn, claim_id=claim, base_commit_sha=SNAP)
    result = classify_overlap(
        conn,
        target_ids=[target],
        integration_target="main",
        candidate_item_id=43,
    )
    assert result is OverlapClassification.INCOMPATIBLE


def test_thaw_revalidation_demotes_overlapping_active_claim(conn):
    actor = local_human(conn)
    frozen_item = seed_item(conn, item_id=44)
    live_item = seed_item(conn, item_id=45)
    target = seed_target(conn, path_string="src/thaw_overlap.py")
    frozen_claim = register(
        conn,
        actor_id=actor,
        item_id=frozen_item,
        integration_target="main",
        target_ids=[target],
    )
    activate(conn, claim_id=frozen_claim, base_commit_sha=SNAP)
    _freeze(conn, frozen_item)
    live_claim = register(
        conn,
        actor_id=actor,
        item_id=live_item,
        integration_target="main",
        target_ids=[target],
    )
    activate(conn, claim_id=live_claim, base_commit_sha=SNAP)

    demoted = revalidate_item_path_claims_on_thaw(frozen_item)

    assert demoted == (frozen_claim,)
    parked = conn.execute(
        "SELECT id, state, blocked_reason FROM path_claims WHERE id = %s",
        (frozen_claim,),
    ).fetchone()
    live = conn.execute(
        "SELECT state FROM path_claims WHERE id = %s",
        (live_claim,),
    ).fetchone()
    assert int(parked[0]) == frozen_claim
    assert parked[1] == "blocked"
    assert parked[2] == THAW_OVERLAP_BLOCKED_REASON
    assert live[0] == "active"


def test_thaw_revalidation_keeps_unconflicted_active_claim(conn):
    actor = local_human(conn)
    frozen_item = seed_item(conn, item_id=46)
    target = seed_target(conn, path_string="src/thaw_clear.py")
    claim = register(
        conn,
        actor_id=actor,
        item_id=frozen_item,
        integration_target="main",
        target_ids=[target],
    )
    activate(conn, claim_id=claim, base_commit_sha=SNAP)
    _freeze(conn, frozen_item)

    demoted = revalidate_item_path_claims_on_thaw(frozen_item)

    assert demoted == ()
    row = conn.execute(
        "SELECT state FROM path_claims WHERE id = %s",
        (claim,),
    ).fetchone()
    assert row[0] == "active"


def test_handle_thaw_revalidates_before_clearing_frozen(test_db, monkeypatch):
    seen: list[int] = []
    monkeypatch.setattr(
        "yoke_core.domain.path_claims_thaw.revalidate_item_path_claims_on_thaw",
        lambda item_id: seen.append(int(item_id)) or (),
    )
    monkeypatch.setattr(backlog_update_op, "run_post_db_sync", lambda **_kwargs: 0)
    monkeypatch.setattr(
        backlog_update_op._rendering,
        "_maybe_rebuild_board",
        lambda *_args, **_kwargs: None,
    )
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model, "
        "workspace, offered_at, last_heartbeat) VALUES "
        "(%s, 'claude-code', 'anthropic', 'test', '/tmp', %s, %s) "
        "ON CONFLICT (session_id) DO NOTHING",
        (SESSION, now, now),
    )
    test_db.commit()
    insert_item(test_db, id=47, status="implementing", frozen=1)

    outcome = handle_thaw(
        FunctionCallRequest(
            function="items.thaw.run",
            actor=ActorContext(actor_id="1", session_id=SESSION),
            target=TargetRef(kind="item", item_id=47),
            payload={},
        )
    )

    assert outcome.primary_success, outcome.error
    assert seen == [47]
    assert outcome.result_payload["frozen"] is False
