"""The model catalog follows Yoke's shipped defaults unless an operator overrides it."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest

from yoke_contracts.model_reference_catalog import validate_catalog
from yoke_contracts.model_reference_data import MODEL_RECORDS
from yoke_core.domain import model_reference_shipped as shipped
from yoke_core.domain.model_reference_store import (
    create_model_reference_table,
    latest_revision,
    normalized_catalog,
    publish_catalog,
    revision_at,
    revisions_list,
)
from runtime.api.fixtures import pg_testdb

ORIGINAL = shipped.shipped_catalog()


def _shipped_with_price(price: float):
    records = [record.to_dict() for record in MODEL_RECORDS]
    target = next(row for row in records if row["model_id"] == "gpt-6-sol")
    target["api_price"]["input_per_million_usd"] = price
    return normalized_catalog(records)


@pytest.fixture
def catalog_db():
    conn = sqlite3.connect(":memory:")
    create_model_reference_table(conn)
    yield conn
    conn.close()


def _ship(monkeypatch, catalog) -> None:
    monkeypatch.setattr(shipped, "shipped_catalog", lambda: catalog)


def test_shipped_catalog_validates_for_every_boot():
    """CI refuses a shipped catalog that would stop a boot."""
    records, document = shipped.shipped_catalog()
    assert validate_catalog([record.to_dict() for record in records]) == records
    assert document


def test_empty_store_gets_shipped_catalog_from_the_epoch(catalog_db):
    revision_id = shipped.sync_shipped_catalog(catalog_db)
    latest = latest_revision(catalog_db)
    assert latest["revision_id"] == revision_id
    assert latest["source"] == "shipped"
    assert latest["published_by_actor_id"] is None
    assert latest["effective_at"] == datetime(1970, 1, 1, tzinfo=timezone.utc)
    assert shipped.sync_shipped_catalog(catalog_db) is None
    assert len(revisions_list(catalog_db)) == 1


def test_changed_shipped_catalog_appends_once_and_keeps_past_prices(
    catalog_db, monkeypatch
):
    shipped.sync_shipped_catalog(catalog_db)
    before = datetime.now(timezone.utc)
    original = revision_at(catalog_db, before)
    _ship(monkeypatch, _shipped_with_price(3.0))
    appended = shipped.sync_shipped_catalog(catalog_db)
    assert appended is not None
    assert shipped.sync_shipped_catalog(catalog_db) is None
    assert len(revisions_list(catalog_db)) == 2
    latest = latest_revision(catalog_db)
    assert latest["source"] == "shipped"
    price = next(r for r in latest["records"] if r.model_id == "gpt-6-sol")
    assert price.api_price.input_per_million_usd == 3.0
    # A session that started before the new build keeps its revision.
    assert revision_at(catalog_db, before)["revision_id"] == original["revision_id"]


def test_older_build_booting_after_a_newer_one_appends_nothing(
    catalog_db, monkeypatch
):
    shipped.sync_shipped_catalog(catalog_db)
    _ship(monkeypatch, _shipped_with_price(3.0))
    newer = shipped.sync_shipped_catalog(catalog_db)
    _ship(monkeypatch, ORIGINAL)
    assert shipped.sync_shipped_catalog(catalog_db) is None
    assert latest_revision(catalog_db)["revision_id"] == newer


def test_operator_override_holds_until_follow_shipped(catalog_db, monkeypatch):
    shipped.sync_shipped_catalog(catalog_db)
    base = latest_revision(catalog_db)
    candidate = [record.to_dict() for record in base["records"]]
    next(r for r in candidate if r["model_id"] == "gpt-6-sol")["api_price"][
        "input_per_million_usd"
    ] = 9.0
    override = publish_catalog(
        catalog_db,
        candidate,
        effective_at=None,
        actor_id=7,
        source="operator",
        source_note="Negotiated price",
        expected_base_revision_id=base["revision_id"],
    )
    assert shipped.shipped_defaults_differ(catalog_db) is True
    _ship(monkeypatch, _shipped_with_price(4.0))
    assert shipped.sync_shipped_catalog(catalog_db) is None
    assert latest_revision(catalog_db)["revision_id"] == override["revision_id"]

    followed = shipped.follow_shipped_catalog(catalog_db, actor_id=7)
    assert followed["appended"] is True
    assert followed["diff"]["changed"] == ["gpt-6-sol"]
    latest = latest_revision(catalog_db)
    assert latest["source"] == "shipped"
    assert latest["published_by_actor_id"] == 7
    assert shipped.shipped_defaults_differ(catalog_db) is None
    again = shipped.follow_shipped_catalog(catalog_db, actor_id=7)
    assert again["appended"] is False
    assert again["revision_id"] == latest["revision_id"]
    # Following again means later builds keep the catalog current.
    _ship(monkeypatch, _shipped_with_price(5.0))
    assert shipped.sync_shipped_catalog(catalog_db) is not None


def test_override_equal_to_shipped_still_reports_it_will_not_follow(catalog_db):
    shipped.sync_shipped_catalog(catalog_db)
    base = latest_revision(catalog_db)
    publish_catalog(
        catalog_db,
        [record.to_dict() for record in base["records"]],
        effective_at=None,
        actor_id=7,
        source="operator",
        source_note="Pinned",
        expected_base_revision_id=base["revision_id"],
    )
    assert shipped.shipped_defaults_differ(catalog_db) is False
    followed = shipped.follow_shipped_catalog(catalog_db, actor_id=7)
    assert followed["appended"] is True
    assert followed["diff"]["changed"] == []


def test_concurrent_boots_append_exactly_one_revision(test_db, monkeypatch):
    test_db.execute("DELETE FROM model_reference_revisions")
    shipped.sync_shipped_catalog(test_db)
    _ship(monkeypatch, _shipped_with_price(3.0))
    database = test_db.execute("SELECT current_database()").fetchone()[0]
    barrier = Barrier(2)

    def boot():
        with pg_testdb.connect_test_database(database) as conn:
            barrier.wait()
            return shipped.sync_shipped_catalog(conn)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: boot(), range(2)))
    assert sum(result is not None for result in results) == 1
    assert len(revisions_list(test_db)) == 2
