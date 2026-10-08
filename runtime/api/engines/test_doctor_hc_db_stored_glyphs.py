"""HC-stored-glyph-contract fails on stored glyphs the contract refuses.

Writers refuse an unsafe glyph, so the seeded violations below go in as raw
rows — the shape of data stored before its writer checked.
"""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.workflow_definition_codec import canonical_definition_json
from yoke_core.engines.doctor_hc_db_stored_glyphs import (
    HC_SLUG,
    hc_stored_glyph_contract,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

_UNSAFE = "\U0001f3d7\ufe0f"  # building construction + VS16


@pytest.fixture
def conn():
    db_name = pg_testdb.create_test_database()
    try:
        connection = pg_testdb.connect_test_database(db_name)
        try:
            apply_fixture_schema(connection)
            seed_project_identities(connection)
            connection.commit()
            yield connection
        finally:
            connection.close()
    finally:
        pg_testdb.drop_test_database(db_name)


def _run(conn):
    rec = RecordCollector()
    hc_stored_glyph_contract(conn, DoctorArgs(), rec)
    (result,) = rec.results
    assert result.check_id == HC_SLUG
    return result


def _seed_level_glyph(conn, glyph: str) -> None:
    settings = {"level_metadata": {"RESEARCH": {"label": "RESEARCH", "glyph": glyph}}}
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings, created_at) "
        "VALUES (1, 'session-routing', %s, '2026-10-08T00:00:00Z')",
        (json.dumps(settings),),
    )


def _seed_workflow_stage_glyph(conn, glyph: str) -> None:
    definition = deepcopy(builtin_workflow_definition("dash")["definition"])
    definition["stages"][0]["glyph"] = glyph
    conn.execute(
        "INSERT INTO workflow_versions "
        "(workflow_id, version, definition_schema_version, definition_json, "
        "definition_digest, published_at, immutable_at) "
        "VALUES ('dash', 999, %s, %s, %s, '2026-10-08T00:00:00Z', "
        "'2026-10-08T00:00:00Z')",
        (
            int(definition["schema_version"]),
            canonical_definition_json(definition),
            "f" * 64,
        ),
    )


def test_a_clean_universe_passes(conn) -> None:
    _seed_level_glyph(conn, "\U0001f52c")
    result = _run(conn)
    assert result.result == "PASS", result.detail


def test_each_stored_violation_fails_with_its_location_and_correction(conn) -> None:
    conn.execute("UPDATE projects SET emoji = %s WHERE slug = 'yoke'", (_UNSAFE,))
    _seed_level_glyph(conn, "⚠")
    _seed_workflow_stage_glyph(conn, "▫")

    result = _run(conn)

    assert result.result == "FAIL"
    assert "3 stored glyph(s)" in result.detail
    assert "projects.emoji for project yoke" in result.detail
    assert (
        "yoke projects update --slug yoke --name Yoke --emoji <glyph>" in result.detail
    )
    assert "level_metadata.RESEARCH.glyph in project yoke" in result.detail
    assert (
        "--cap-type session-routing --set level_metadata.RESEARCH.glyph=<glyph>"
        in result.detail
    )
    assert "workflow dash v999 stages[0].glyph" in result.detail
    assert "yoke workflows canon-update apply dash" in result.detail
    assert "U+FE0F" in result.detail


def test_an_empty_project_emoji_is_not_a_glyph(conn) -> None:
    conn.execute("UPDATE projects SET emoji = '' WHERE slug = 'yoke'")
    assert _run(conn).result == "PASS"
