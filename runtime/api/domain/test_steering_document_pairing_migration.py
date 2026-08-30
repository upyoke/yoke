"""Backfill coverage for steering seats created before document pairing."""

from __future__ import annotations

from yoke_contracts.steering_claims import DEFAULT_STEERING_DOC_SLUG
from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.strategy_execution import acquire_session_doc_claim
from yoke_core.domain.work_claim_targets import make_steering_target

from runtime.api.domain.steering_claim_test_support import (
    PROJECT_ALPHA,
    SESSION_ALPHA,
    seed_standard_steering_world,
)


ENTRY_NAME = "0027_pair_steering_document_claims"


def _entry():
    directory = history_dir(migration_history_package)
    record = next(
        entry for entry in ordered_entries(directory) if entry.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{record.name}.py", record.name)


entry = _entry()


def _insert_legacy_seat(conn) -> int:
    now = iso8601_now()
    row = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat) "
        "VALUES (%s, 'steering', %s, 'exclusive', %s, %s) RETURNING id",
        (
            SESSION_ALPHA,
            make_steering_target(PROJECT_ALPHA).scope_json(),
            now,
            now,
        ),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def test_existing_session_document_becomes_the_active_pair(test_db) -> None:
    seed_standard_steering_world(test_db)
    document = acquire_session_doc_claim(
        test_db,
        project_id=PROJECT_ALPHA,
        slug=DEFAULT_STEERING_DOC_SLUG,
        session_id=SESSION_ALPHA,
        actor_id=2,
    )
    claim_id = _insert_legacy_seat(test_db)

    entry.apply(test_db)
    entry.invariants(test_db)

    row = test_db.execute(
        "SELECT paired_work_claim_id FROM strategy_doc_claims WHERE id = %s",
        (int(document["id"]),),
    ).fetchone()
    assert int(row["paired_work_claim_id"]) == claim_id


def test_missing_document_lock_is_created_from_the_default_doc(test_db) -> None:
    seed_standard_steering_world(test_db)
    claim_id = _insert_legacy_seat(test_db)

    entry.apply(test_db)
    entry.apply(test_db)
    entry.invariants(test_db)

    row = test_db.execute(
        "SELECT strategy_doc_slug, owner_session_id FROM strategy_doc_claims "
        "WHERE paired_work_claim_id = %s AND released_at IS NULL",
        (claim_id,),
    ).fetchone()
    assert row["strategy_doc_slug"] == DEFAULT_STEERING_DOC_SLUG
    assert row["owner_session_id"] == SESSION_ALPHA
