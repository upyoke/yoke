"""Event-emission, upsert, and read-helper coverage for db_claim.amend / read_claim.

Validation/atomicity/input-discipline tests live in test_db_claim.py.
The local ``db_conn`` fixture delegates to the canonical Postgres
``test_db`` fixture so this sibling stays self-contained while exercising
the same native backend production runs on.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.db_claim import (
    DbClaimAmendmentError,
    amend,
    read_claim,
)
from yoke_core.domain.db_compatibility_attestation import FREEZE_FIELD
from runtime.api.fixtures.backlog import insert_item, test_db


@pytest.fixture
def db_conn(test_db):  # noqa: F811 - fixture imported for pytest discovery
    """Postgres-backed connection with the full Yoke schema."""
    yield test_db


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _declared_payload(**overrides) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "state": "declared",
        "model_name": "primary",
        "mutation_intent": "apply",
        "migration_modules": ["add_items_due_date"],
        "compatibility_class": "pre_merge_safe",
        "migration_strategy": "additive_only",
        "schema_kinds": ["additive"],
        "affected_surfaces": [{"table": "items", "columns": ["due_date"]}],
        "pre_merge_readers_writers": [
            {"path": "runtime/api/domain/items.py", "role": "writer"}
        ],
        "invariants": ["items.due_date nullable after apply"],
        "rehearsal_commands": ["python3 -m pytest runtime/api/"],
        "residual_risk_notes": "none",
    }
    base.update(overrides)
    return base


def _fetch_fields(conn: Any, item_id: int) -> Dict[str, Any]:
    p = _placeholder(conn)
    row = conn.execute(
        "SELECT db_mutation_profile, db_compatibility_attestation "
        f"FROM items WHERE id = {p}",
        (item_id,),
    ).fetchone()
    return {
        "profile": json.loads(row["db_mutation_profile"]),
        "attestation": json.loads(row["db_compatibility_attestation"]),
    }


# ---------------------------------------------------------------------------
# Upsert semantics — idea late classification
# ---------------------------------------------------------------------------


class TestUpsert:
    def test_amend_on_fresh_item_with_negative_default(self, db_conn):
        """Idea-time classification writes against the negative default
        without needing a pre-existing declared claim."""
        insert_item(db_conn, id=500, status="idea")
        amend(
            500,
            _declared_payload(migration_modules=["m1"]),
            reason="idea late classification",
            conn=db_conn,
        )
        stored = _fetch_fields(db_conn, 500)
        assert stored["profile"]["migration_modules"] == ["m1"]

    def test_ac_17_flip_state_none_with_frozen_to_declared(self, db_conn):
        """AC-17: existing refining-idea row with state=none + frozen_at
        can flip to state=declared via the workflow without rollback."""
        insert_item(
            db_conn,
            id=501,
            status="refining-idea",
            db_mutation_profile='{"state":"none"}',
            db_compatibility_attestation='{"frozen_at":"2026-04-23T22:01:29Z"}',
        )
        result = amend(
            501,
            _declared_payload(),
            reason="discovered governed DB mutation mid-refine",
            conn=db_conn,
        )
        stored = _fetch_fields(db_conn, 501)
        assert stored["profile"]["state"] == "declared"
        assert stored["attestation"][FREEZE_FIELD]
        assert stored["attestation"][FREEZE_FIELD] != "2026-04-23T22:01:29Z"
        rows = db_conn.execute(
            "SELECT event_name, item_id FROM events "
            f"WHERE event_name = 'DbClaimAmended' AND item_id = {_placeholder(db_conn)}",
            ("501",),
        ).fetchall()
        assert len(rows) == 1
        assert result.event_id is not None


# ---------------------------------------------------------------------------
# Event emission contents
# ---------------------------------------------------------------------------


class TestEventEmission:
    def test_event_envelope_carries_claim_summaries(self, db_conn):
        insert_item(db_conn, id=600, status="refining-idea")
        amend(
            600,
            _declared_payload(),
            reason="first declaration",
            conn=db_conn,
        )
        row = db_conn.execute(
            "SELECT envelope FROM events WHERE event_name='DbClaimAmended' "
            f"AND item_id={_placeholder(db_conn)}",
            ("600",),
        ).fetchone()
        assert row is not None
        envelope = json.loads(row["envelope"])
        context = envelope["context"]
        assert context["reason"] == "first declaration"
        assert context["validation_result"] == "pass"
        assert context["previous_profile"] == {"state": "none"}
        assert context["new_profile"]["state"] == "declared"

    def test_event_uses_items_project(self, db_conn):
        insert_item(db_conn, id=601, status="refining-idea", project="externalwebapp")
        amend(
            601,
            _declared_payload(),
            reason="cross-project declaration",
            conn=db_conn,
        )
        row = db_conn.execute(
            "SELECT e.project_id, p.slug AS project, e.envelope "
            "FROM events e JOIN projects p ON p.id = e.project_id "
            "WHERE e.event_name='DbClaimAmended' "
            f"AND e.item_id={_placeholder(db_conn)}",
            ("601",),
        ).fetchone()
        assert row is not None
        assert row["project_id"] == 2
        assert row["project"] == "externalwebapp"
        envelope = json.loads(row["envelope"])
        assert envelope["project"] == "externalwebapp"

    def test_event_emission_failure_rolls_back_amendment(self, db_conn):
        insert_item(db_conn, id=602, status="refining-idea")
        db_conn.execute("DROP TABLE events")
        with pytest.raises(DbClaimAmendmentError) as exc_info:
            amend(
                602,
                _declared_payload(),
                reason="must keep audit history",
                conn=db_conn,
            )
        assert "DbClaimAmended event emission failed" in str(exc_info.value)
        stored = _fetch_fields(db_conn, 602)
        assert stored["profile"] == {"state": "none"}
        assert stored["attestation"] == {}

    def test_db_claim_amended_registered_in_event_metadata(self):
        from yoke_core.domain.populate_registry import AUTHORITATIVE_METADATA

        registered = {entry[0]: entry for entry in AUTHORITATIVE_METADATA}
        assert "DbClaimAmended" in registered
        assert registered["DbClaimAmended"][1:4] == (
            "workflow",
            "db_claim_amendment",
            "yoke_core.domain.db_claim",
        )


# ---------------------------------------------------------------------------
# Read helper
# ---------------------------------------------------------------------------


class TestReadClaim:
    def test_read_claim_returns_profile_and_attestation(self, db_conn):
        insert_item(db_conn, id=700, status="refining-idea")
        claim = read_claim(700, conn=db_conn)
        assert claim["profile"] == {"state": "none"}
        assert claim["attestation"] == {}

    def test_read_claim_missing_item_raises(self, db_conn):
        with pytest.raises(DbClaimAmendmentError):
            read_claim(9999, conn=db_conn)
