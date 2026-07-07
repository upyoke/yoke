"""End-to-end producer→consumer test for the field-note channel.

Exercises the full loop: agent dispatches four ``ouroboros.field_note.append``
calls (one per kind: ``failed``, ``new``, ``unclear``, ``observation``)
through the canonical function-call surface; the ``/yoke curate`` consumer
surface — the ``ouroboros list-entries --unreviewed`` query the skill body
runs — surfaces all four rows from ``ouroboros_entries`` where
``category LIKE 'field-note-%'``.

Per FR-4 of YOK-1872, curate now reads from the ``ouroboros_entries`` table
(filter: ``category LIKE 'field-note-%'``), not from the events stream. The
``ouroboros_entries`` row is the AUTHORITATIVE store; the
``OuroborosFieldNoteAppended`` event is best-effort telemetry. This test
never reads the events table.

The curate skill is prompt-driven (LLM-as-clusterer); its consumer surface
is :func:`yoke_core.domain.ouroboros_entries.cmd_list_entries`, which the
``python3 -m yoke_core.cli.db_router ouroboros list-entries --unreviewed``
shell entry wraps.
"""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import pytest

from yoke_core.domain import schema
from yoke_core.domain.db_helpers import connect, iso8601_now
from runtime.api.fixtures.file_test_db import init_test_db
from yoke_core.domain.handlers import ouroboros_field_note as _ofn
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.ouroboros_entries import cmd_insert_entry, cmd_list_entries
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests


SESSION_ID = "session-field-note-loop"

# Distinctive evidence text — each carries a unique substring so we can
# assert per-kind round-trip without ambiguity. One row per kind in
# FIELD_NOTE_KIND_VALUES.
SEEDS: Tuple[Tuple[str, str], ...] = (
    ("failed", "R-CL-03 path-claim-narrow recipe used --remove; actual flag is --drop-paths"),
    ("new", "missing recipe for harness session resume after laptop sleep cycle"),
    ("unclear", "purpose unclear for R-OP-04 — does the paste preserve PYTHONPATH or not?"),
    ("observation", "minor inconsistency in event-catalog row ordering noticed during read"),
)


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Bootstrap a fresh Yoke schema and pin YOKE_DB. The handler resolves
    the DB via :func:`db_helpers.connect`, which honours ``YOKE_DB``; the test
    queries through the same path.

    On Postgres the schema lands in a disposable per-test database (YOKE_PG_DSN
    repointed for the context's lifetime) so concurrent ``-n`` workers do not
    collide on the shared ambient DB; on SQLite it is a file under ``tmp_path``.
    """
    with init_test_db(tmp_path, apply_schema=schema.cmd_init) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


@pytest.fixture
def registered_dispatcher() -> None:
    """Reset + register the full handler registry so dispatch() resolves
    ``ouroboros.field_note.append``. Idempotent across tests."""
    reset_registry_for_tests()
    register_all_handlers()
    yield
    reset_registry_for_tests()


def _build_request(kind: str, evidence: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="ouroboros.field_note.append",
        actor=ActorContext(session_id=SESSION_ID),
        target=TargetRef(kind="global"),
        payload={"kind": kind, "evidence": evidence},
    )


def _seed_via_dispatch() -> list[str]:
    """Producer side: dispatch four field-note appends and return entry ids."""
    entry_ids: list[str] = []
    for kind, evidence in SEEDS:
        response = dispatch(
            _build_request(kind, evidence),
            ambient_session_id=SESSION_ID,
        )
        assert response.success is True, (
            f"dispatch for kind={kind!r} failed: {response.error}"
        )
        assert response.function == "ouroboros.field_note.append"
        entry_ids.append(response.result["entry_id"])
    return entry_ids


def _query_curate_consumer_rows(db_path: str) -> str:
    """Consumer side: the exact query `/yoke curate` runs to surface
    field-note signals. Returns the pipe-delimited row list — same shape
    the operator sees from
    ``db_router ouroboros list-entries --unreviewed``."""
    with connect(db_path) as conn:
        return cmd_list_entries(conn, unreviewed=True)


def _query_field_note_rows(db_path: str) -> list[tuple[str, str, str]]:
    """Direct table read filtered on ``category LIKE 'field-note-%'`` —
    this is the canonical filter the curate skill applies. Returns
    ``(category, body, agent)`` tuples for assertion against SEEDS."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT category, body, agent FROM ouroboros_entries "
            "WHERE category LIKE 'field-note-%' ORDER BY id ASC"
        ).fetchall()
    return [(row[0], row[1], row[2]) for row in rows]


class TestFieldNoteCurateLoop:
    """Producer (function-call dispatch) → consumer (curate table read)."""

    def test_four_kinds_round_trip_through_curate_list_entries(
        self,
        isolated_db: str,
        registered_dispatcher: None,
    ) -> None:
        entry_ids = _seed_via_dispatch()
        assert len(entry_ids) == 4
        assert len(set(entry_ids)) == 4, "each dispatch produced a unique entry_id"

        rows_text = _query_curate_consumer_rows(isolated_db)
        assert rows_text, "curate-side list-entries returned no rows"
        row_lines = rows_text.split("\n")
        assert len(row_lines) == 4, (
            "curate query should surface 4 field-note rows; "
            f"got {len(row_lines)}"
        )
        # The format includes the category column; every surfaced row
        # must carry a field-note-* category so the curate filter
        # (``category LIKE 'field-note-%'``) matches.
        for line in row_lines:
            assert "|field-note-" in line, (
                f"row missing field-note-* category marker: {line!r}"
            )

    def test_evidence_text_survives_round_trip_per_kind(
        self,
        isolated_db: str,
        registered_dispatcher: None,
    ) -> None:
        _seed_via_dispatch()
        rows = _query_field_note_rows(isolated_db)
        assert len(rows) == 4, (
            f"table read should return one ouroboros_entries row per "
            f"seeded entry; got {len(rows)}"
        )
        recovered = {category: body for category, body, _agent in rows}
        expected = {f"field-note-{kind}": evidence for kind, evidence in SEEDS}
        assert recovered == expected, (
            "evidence text or category drifted on round trip; "
            f"expected={expected!r} recovered={recovered!r}"
        )

    def test_category_filter_matches_field_note_prefix(
        self,
        isolated_db: str,
        registered_dispatcher: None,
    ) -> None:
        """Curate's filter is ``category LIKE 'field-note-%'``. Verify the
        handler writes categories with that prefix for every kind in the
        canonical vocabulary."""
        _seed_via_dispatch()
        rows = _query_field_note_rows(isolated_db)
        categories = {row[0] for row in rows}
        expected_categories = {
            f"field-note-{kind}" for kind in _ofn.FIELD_NOTE_KIND_VALUES
        }
        assert categories == expected_categories, (
            "handler-written categories do not match canonical "
            "field-note-<kind> vocabulary; "
            f"expected={expected_categories!r} got={categories!r}"
        )

    def test_seeded_row_is_surfaced_by_curate_list_entries(
        self,
        isolated_db: str,
    ) -> None:
        """Minimal seed-then-read path: insert one ``ouroboros_entries``
        row with ``category='field-note-observation'`` directly (bypassing
        the dispatcher) and assert ``cmd_list_entries`` surfaces it.
        Proves the curate consumer surface reads field-note rows from the
        table, independent of the function-call producer path."""
        with connect(isolated_db) as conn:
            entry_id = cmd_insert_entry(
                conn,
                iso8601_now(),
                "engineer",
                None,
                "field-note-observation",
                "neutral observation: doc cross-reference noticed during read",
            )
        assert entry_id and entry_id != "Duplicate entry skipped"

        rows_text = _query_curate_consumer_rows(isolated_db)
        assert rows_text, "curate consumer surface returned no rows"
        assert "|field-note-observation|" in rows_text, (
            "seeded field-note-observation row not surfaced by "
            f"cmd_list_entries; rows_text={rows_text!r}"
        )
