"""Session costs share immutable catalogs and travel as named facts."""

import json
from datetime import timedelta

import pytest

from yoke_contracts.board.data import _encode_value, _decode_value
from yoke_contracts.board.sections_sessions import collect_session_rows
from yoke_contracts.board.session_data import render_session_rows
from yoke_contracts.board.sections_sessions_cells import _display_usage
from yoke_contracts.model_reference_data import MODEL_RECORDS
from yoke_contracts.session_usage_display import usage_cell
from yoke_contracts.session_usage_facts import ModelUsage, SessionUsage, usage_document
from yoke_contracts.session_usage_pricing import estimated_session_cost
from yoke_contracts.timestamps import parse_instant


class CatalogDB:
    def __init__(self):
        self.boundary = parse_instant("2026-09-01T00:00:00Z")
        self.records = {
            "older": [record.to_dict() for record in MODEL_RECORDS],
            "newer": [record.to_dict() for record in MODEL_RECORDS],
        }
        for record in self.records["newer"]:
            if record.get("api_price"):
                record["api_price"]["input_per_million_usd"] = 123.0
        self.catalog_reads = []

    def query(self, sql, params):
        if "effective_at <= %s" in sql:
            when = params[0]
            revision = "older" if when < self.boundary else "newer"
            effective = (
                self.boundary - timedelta(days=1)
                if revision == "older"
                else self.boundary
            )
            return [(revision, effective)]
        revision = params[0]
        self.catalog_reads.append(revision)
        return [(json.dumps(self.records[revision]),)]


def test_many_sessions_share_catalogs_and_preserve_start_time_costs():
    from yoke_contracts.model_reference_catalog import validate_catalog

    db = CatalogDB()
    usage = SessionUsage(
        status="complete",
        models=(ModelUsage(model=MODEL_RECORDS[0].model_id, input=1_000_000),),
    )
    document = usage_document(usage)
    starts = [db.boundary + timedelta(seconds=index - 100) for index in range(200)]
    cells = [_display_usage(db, document, start) for start in starts]
    assert db.catalog_reads == ["older", "newer"]
    assert cells[0] != cells[-1]
    for start, cell in zip(starts, cells):
        revision = "older" if start < db.boundary else "newer"
        expected = estimated_session_cost(
            usage,
            {
                "revision_id": revision,
                "effective_at": db.boundary,
                "records": validate_catalog(db.records[revision]),
            },
        )
        assert cell == usage_cell(usage, expected)


def test_live_session_table_carries_one_catalog(tmp_path, monkeypatch):
    from runtime.api.board.tests.sessions_render_test_support import make_render_db
    from runtime.api.fixtures.file_test_db import connect_test_db
    from yoke_contracts.timestamps import utc_now

    with make_render_db(tmp_path) as (db, render):
        now = utc_now()
        monkeypatch.setattr(
            "yoke_contracts.board.sections_sessions_rendering.utc_now", lambda: now
        )
        usage = usage_document(
            SessionUsage(
                status="complete",
                models=(ModelUsage(model=MODEL_RECORDS[0].model_id, input=1_000),),
            )
        )
        with connect_test_db(db.path) as conn:
            for index in range(100):
                conn.execute(
                    "INSERT INTO harness_sessions "
                    "(session_id,executor,project_id,offered_at,last_heartbeat,usage_totals) "
                    "VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        f"live-session-{index}",
                        "codex",
                        1,
                        now - timedelta(seconds=index),
                        now,
                        usage,
                    ),
                )
        direct = render(db)
        facts = collect_session_rows(db, scope="all", active_only=True)
        wire = json.dumps(_encode_value(facts))
        assert "catalog_json" not in wire
        assert len(wire.encode()) < 100_000
        assert render_session_rows(_decode_value(json.loads(wire)), []) == direct
        assert "live-session-99" in direct


def test_missing_effective_revision_teaches_publication():
    class EmptyDB:
        def query(self, sql, params):
            return []

    with pytest.raises(ValueError, match="no model catalog revision.*publish one"):
        _display_usage(EmptyDB(), None, parse_instant("2026-09-01T00:00:00Z"))
