"""Migration territory frees when the item's merge lands, not at delivery.

Once an entry is in the base branch's history, the next migration item rebases
onto it and rehearses its own entry. Nothing after the merge reads the hold, so
a queue of migration items no longer needs one release per item: the release
fleet preflight converges every unreleased entry the build carries.
"""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally re-exported.

from __future__ import annotations

from contextlib import contextmanager

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.coordination_claims import active_claim, get_claim
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.handlers import item_landings_ops
from yoke_core.domain.item_landings_schema import (
    ROUTE_STANDALONE,
    ensure_item_landings_schema,
)
from yoke_core.domain.migration_apply_rehearse import rehearse
from yoke_core.domain.work_claim_targets import (
    make_migration_serialization_target,
)
from runtime.api.domain.migration_apply_test_helpers import (  # noqa: F401 — fixtures
    _seed_apply_item,
    apply_env,
)
from runtime.api.domain.migration_boot_test_helpers import (
    RESTORE_POINT,
    apply_pending,
    connection,
    history,
    marks,
    pending_entries,
)
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401 — reused fixtures

MERGE_SHA = "a" * 40


def _held(control_db: str):
    conn = connect(control_db)
    try:
        return active_claim(conn, make_migration_serialization_target(1, "primary", 1))
    finally:
        conn.close()


def _record_landing(monkeypatch, control_db: str, item_id: int):
    @contextmanager
    def _connect_rw():
        conn = connect(control_db)
        try:
            ensure_item_landings_schema(conn)
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(item_landings_ops, "_connect_rw", _connect_rw)
    return item_landings_ops.handle_record_item_landing(
        FunctionCallRequest(
            function="item_landings.record",
            actor=ActorContext(actor_id=None, session_id="session-a"),
            target=TargetRef(kind="item", item_id=item_id),
            payload={
                "merge_sha": MERGE_SHA,
                "route": ROUTE_STANDALONE,
                "landed_at": "2026-10-07T00:00:00Z",
                "target_branch": "main",
            },
        )
    )


def _rehearse(apply_env, item_id: int, session_id: str):
    return rehearse(
        item_id,
        session_id=session_id,
        control_db_path=apply_env["control_db"],
        worktree_path=apply_env["worktree"],
    )


def test_landing_frees_territory_for_the_next_item(apply_env, monkeypatch) -> None:
    _seed_apply_item(apply_env["control_db"], item_id=6101)
    first = _rehearse(apply_env, 6101, "session-a")
    assert first.all_succeeded and _held(apply_env["control_db"]) is not None

    outcome = _record_landing(monkeypatch, apply_env["control_db"], 6101)

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["migration_territory_released"] == first.lease_id
    assert _held(apply_env["control_db"]) is None
    conn = connect(apply_env["control_db"])
    try:
        settled = get_claim(conn, first.lease_id)
    finally:
        conn.close()
    assert settled.release_reason_intent == f"item-landed:{MERGE_SHA}"

    # The first item is merged but not delivered; the second still rehearses.
    _seed_apply_item(apply_env["control_db"], item_id=6102)
    second = _rehearse(apply_env, 6102, "session-b")

    assert second.all_succeeded
    held = _held(apply_env["control_db"])
    assert held is not None and held.owner_item_id == 6102


def test_a_landing_without_territory_releases_nothing(apply_env, monkeypatch) -> None:
    _seed_apply_item(apply_env["control_db"], item_id=6103)

    outcome = _record_landing(monkeypatch, apply_env["control_db"], 6103)

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["appended"] is True
    assert outcome.result_payload["migration_territory_released"] is None


def test_re_recorded_landing_does_not_touch_another_items_territory(
    apply_env, monkeypatch
) -> None:
    _seed_apply_item(apply_env["control_db"], item_id=6104)
    _seed_apply_item(apply_env["control_db"], item_id=6105)
    assert _rehearse(apply_env, 6104, "session-a").all_succeeded
    assert _record_landing(monkeypatch, apply_env["control_db"], 6104).primary_success
    second = _rehearse(apply_env, 6105, "session-b")

    again = _record_landing(monkeypatch, apply_env["control_db"], 6104)

    assert again.result_payload["appended"] is False
    assert again.result_payload["migration_territory_released"] is None
    held = _held(apply_env["control_db"])
    assert held is not None and held.id == second.lease_id


def test_release_converge_covers_every_merged_unreleased_entry(tmp_path) -> None:
    # Two items merged back to back; neither has been released. The build the
    # release carries holds both, and the fleet preflight's boot converge
    # applies both to every universe it rehearses.
    entries = history(tmp_path, "0001_first_landed", "0002_second_landed")
    conn = connection()

    assert [e.name for e in pending_entries(conn, entries)] == [
        "0001_first_landed",
        "0002_second_landed",
    ]
    outcome = apply_pending(
        conn,
        history=entries,
        applied_by="test",
        running_version="",
        external_restore_point=RESTORE_POINT,
    )

    assert outcome.applied == ("0001_first_landed", "0002_second_landed")
    assert marks(conn) == ["0001_first_landed", "0002_second_landed"]
    assert pending_entries(conn, entries) == ()
