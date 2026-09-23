"""Published price revisions keep session estimates stable over time."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.model_reference_catalog import validate_catalog
from yoke_contracts.model_reference_records import ModelReferenceError
from yoke_contracts.session_usage_facts import ModelUsage, SessionUsage, USAGE_COMPLETE
from yoke_contracts.session_usage_pricing import estimated_session_cost
from yoke_core.domain.model_reference_store import (
    create_model_reference_table,
    latest_revision,
    publish_catalog,
    revision_at,
    revision_get,
    seed_initial_catalog,
)


@pytest.fixture
def catalog_db():
    conn = sqlite3.connect(":memory:")
    create_model_reference_table(conn)
    seed_initial_catalog(conn)
    yield conn
    conn.close()


def _candidate(conn):
    return [record.to_dict() for record in revision_at(conn)["records"]]


def _future(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def test_revision_effective_at_preserves_earlier_sessions(catalog_db):
    original = revision_at(catalog_db)
    candidate = _candidate(catalog_db)
    target = next(row for row in candidate if row["model_id"] == "gpt-6-sol")
    target["api_price"]["input_per_million_usd"] = 3.0
    effective = _future(2)
    published = publish_catalog(
        catalog_db,
        candidate,
        effective_at=effective,
        actor_id=1,
        source_note="Provider price update checked against official source",
        expected_base_revision_id=original["revision_id"],
    )

    assert revision_at(catalog_db, _future(1))["revision_id"] == original["revision_id"]
    assert revision_at(catalog_db, effective)["revision_id"] == published["revision_id"]
    assert (
        revision_at(catalog_db, _future(3))["revision_id"] == published["revision_id"]
    )
    usage = SessionUsage(
        status=USAGE_COMPLETE,
        source="test reading",
        models=(ModelUsage(model="gpt-6-sol", input=1_000_000),),
    )
    earlier = estimated_session_cost(usage, revision_at(catalog_db, _future(1)))
    later = estimated_session_cost(usage, revision_at(catalog_db, _future(3)))
    assert earlier.usd == 2.0
    assert later.usd == 3.0
    assert earlier.revision_id == original["revision_id"]
    assert later.revision_id == published["revision_id"]
    # A resumed episode does not change the session's initial pricing basis.
    session_offered_at = _future(1)
    episode_started_at = _future(3)
    assert episode_started_at > effective
    resumed = estimated_session_cost(usage, revision_at(catalog_db, session_offered_at))
    assert resumed.revision_id == original["revision_id"]
    assert (
        revision_get(catalog_db, original["revision_id"])["revision_id"]
        == original["revision_id"]
    )
    seed_initial_catalog(catalog_db)
    assert (
        revision_at(catalog_db, _future(3))["revision_id"] == published["revision_id"]
    )


def test_past_publication_cannot_change_started_session_price(catalog_db):
    original = revision_at(catalog_db)
    with pytest.raises(ModelReferenceError, match="predates publication"):
        publish_catalog(
            catalog_db,
            _candidate(catalog_db),
            effective_at="2025-01-01T00:00:00Z",
            actor_id=1,
            source_note="A correction from an earlier source",
            expected_base_revision_id=original["revision_id"],
        )


def test_scheduled_catalog_is_publication_base(catalog_db):
    original = revision_at(catalog_db)
    candidate = _candidate(catalog_db)
    scheduled = publish_catalog(
        catalog_db,
        candidate,
        effective_at=_future(2),
        actor_id=1,
        source_note="Provider research",
        expected_base_revision_id=original["revision_id"],
    )
    assert revision_at(catalog_db)["revision_id"] == original["revision_id"]
    assert latest_revision(catalog_db)["revision_id"] == scheduled["revision_id"]
    with pytest.raises(ModelReferenceError, match="latest catalog changed"):
        publish_catalog(
            catalog_db,
            candidate,
            effective_at=_future(3),
            actor_id=1,
            source_note="Second provider research",
            expected_base_revision_id=original["revision_id"],
        )
    with pytest.raises(ModelReferenceError, match="latest scheduled revision"):
        publish_catalog(
            catalog_db,
            candidate,
            effective_at=_future(1),
            actor_id=1,
            source_note="Second provider research",
            expected_base_revision_id=scheduled["revision_id"],
        )


def test_catalog_rejects_duplicate_launch_aliases(catalog_db):
    candidate = _candidate(catalog_db)
    candidate[1]["aliases"] = [candidate[0]["model_id"]]
    with pytest.raises(ModelReferenceError, match="names both"):
        validate_catalog(candidate)


def test_stale_preview_base_refuses_publication(catalog_db):
    with pytest.raises(ModelReferenceError, match="latest catalog changed"):
        publish_catalog(
            catalog_db,
            _candidate(catalog_db),
            effective_at=_future(1),
            actor_id=1,
            source_note="Provider research",
            expected_base_revision_id="old-preview",
        )
