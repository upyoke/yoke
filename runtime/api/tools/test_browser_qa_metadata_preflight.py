"""Tests for yoke_core.tools.browser_qa_metadata_preflight."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.browser_qa_metadata import (
    NEGATIVE_DEFAULT_JSON,
    canonical_json,
)
from yoke_core.domain.items import insert_item, update_structured_field
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)
from yoke_core.tools.browser_qa_metadata_preflight import (
    find_unset_rows,
    main as preflight_main,
)


def _seed_item(db_path, *, item_id, status, title="Item"):
    insert_item(
        item_id=item_id,
        title=title,
        item_type="issue",
        status=status,
        priority="medium",
        source="user",
        project="yoke",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        db_path=db_path,
    )


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as path:
        yield path


class TestFindUnsetRows:
    def test_all_populated_returns_empty(self, db_path):
        _seed_item(db_path, item_id=1, status="refined-idea")
        update_structured_field(
            1, "browser_qa_metadata", NEGATIVE_DEFAULT_JSON, db_path=db_path,
        )
        assert find_unset_rows(db_path=db_path) == []

    def test_terminal_done_items_exempt(self, db_path):
        _seed_item(db_path, item_id=1, status="done")
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE items SET browser_qa_metadata = NULL WHERE id = 1"
        )
        conn.commit()
        conn.close()
        # Terminal statuses are exempt, so zero findings
        assert find_unset_rows(db_path=db_path) == []

    def test_cancelled_items_exempt(self, db_path):
        _seed_item(db_path, item_id=1, status="cancelled")
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE items SET browser_qa_metadata = '' WHERE id = 1"
        )
        conn.commit()
        conn.close()
        assert find_unset_rows(db_path=db_path) == []

    def test_blocked_is_not_exempt(self, db_path):
        _seed_item(db_path, item_id=1, status="blocked")
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE items SET browser_qa_metadata = NULL WHERE id = 1"
        )
        conn.commit()
        conn.close()
        findings = find_unset_rows(db_path=db_path)
        assert len(findings) == 1
        assert findings[0]["id"] == 1
        assert findings[0]["reason"] == "missing"

    def test_null_string_detected_as_missing(self, db_path):
        _seed_item(db_path, item_id=2, status="implementing")
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE items SET browser_qa_metadata = 'null' WHERE id = 2"
        )
        conn.commit()
        conn.close()
        findings = find_unset_rows(db_path=db_path)
        assert len(findings) == 1
        assert findings[0]["reason"] == "missing"

    def test_invalid_stored_payload_detected(self, db_path):
        _seed_item(db_path, item_id=3, status="refined-idea")
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE items SET browser_qa_metadata = %s WHERE id = 3",
            (json.dumps({"browser_testable": "yes"}),),
        )
        conn.commit()
        conn.close()
        findings = find_unset_rows(db_path=db_path)
        assert len(findings) == 1
        assert findings[0]["reason"].startswith("invalid:")


class TestPreflightMain:
    def test_main_returns_zero_when_clean(self, db_path, monkeypatch, capsys):
        _seed_item(db_path, item_id=1, status="refined-idea")
        update_structured_field(
            1, "browser_qa_metadata", NEGATIVE_DEFAULT_JSON, db_path=db_path,
        )
        rc = preflight_main(["--db", db_path])
        captured = capsys.readouterr()
        assert rc == 0
        assert "all non-terminal items are populated" in captured.out

    def test_main_returns_one_when_findings(self, db_path, capsys):
        _seed_item(db_path, item_id=9, status="implementing", title="needs meta")
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE items SET browser_qa_metadata = NULL WHERE id = 9"
        )
        conn.commit()
        conn.close()
        rc = preflight_main(["--db", db_path])
        captured = capsys.readouterr()
        assert rc == 1
        assert "YOK-9" in captured.err
        assert "BLOCKED" in captured.err
