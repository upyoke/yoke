"""Operational observations do not change portable business authority."""

import pytest

from yoke_core.domain.source_authority_receipts import authority_receipt


@pytest.mark.parametrize("include_content_digests", [False, True])
def test_operational_rows_and_owned_sequences_do_not_change_authority(test_db, include_content_digests):
    test_db.execute("CREATE SCHEMA authority_observation_test")
    test_db.execute("SET search_path TO authority_observation_test")
    test_db.execute("CREATE TABLE items (id BIGSERIAL PRIMARY KEY, title TEXT)")
    transient = ("actor_ui_preferences", "frontend_event_rate_limits", "merge_queue_landing_refreshes")
    for table in transient:
        test_db.execute(f"CREATE TABLE {table} (id BIGSERIAL PRIMARY KEY, value TEXT)")
    test_db.execute("INSERT INTO items (title) VALUES ('saved work')")
    before = authority_receipt(test_db, include_content_digests=include_content_digests)
    for table in transient:
        test_db.execute(f"INSERT INTO {table} (value) VALUES ('observation')")
        test_db.execute(f"UPDATE {table} SET value='refreshed'")
    after = authority_receipt(test_db, include_content_digests=include_content_digests)
    assert before == after
    assert set(after["database_table_catalog"]) == {"items", *transient}
    assert after["portable_table_catalog"] == ["items"]
    assert [entry["owner_table"] for entry in after["sequences"]] == ["items"]
    # Normalization excludes comparison state, without deleting archived rows.
    for table in transient:
        assert test_db.execute(f"SELECT value FROM {table}").fetchone()[0] == "refreshed"
    test_db.execute("INSERT INTO items (title) VALUES ('new work')")
    changed = authority_receipt(test_db, include_content_digests=include_content_digests)
    assert changed["receipt_digest"] != after["receipt_digest"]
