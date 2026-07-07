"""Validation, atomicity, and input-discipline tests for db_claim.amend.

Negative-default and declared-state validation, two-field atomicity, and
reserved-key handling. Event emission, upsert flips, and read_claim
round-trip live in the sibling test_db_claim_events_upsert.py.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.db_claim import (
    DbClaimAmendmentError,
    amend,
)
from yoke_core.domain.db_compatibility_attestation import FREEZE_FIELD
from runtime.api.fixtures.backlog import insert_item, test_db


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@pytest.fixture
def db_conn(test_db):  # noqa: F811 - fixture imported for pytest discovery
    """Postgres-backed connection with the full Yoke schema."""
    yield test_db


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
# Happy path: state=none
# ---------------------------------------------------------------------------


class TestStateNone:
    def test_writes_stamped_negative_claim_and_empty_attestation(self, db_conn):
        insert_item(db_conn, id=100, status="refining-idea")
        result = amend(100, {"state": "none"}, reason="no DB work", conn=db_conn)
        stored = _fetch_fields(db_conn, 100)
        # The amend workflow stamps the reviewed-negative attestation
        # onto the profile — a state="none" amendment IS the operator's
        # reviewed-none decision, recorded as item state (not events).
        assert stored["profile"]["state"] == "none"
        assert stored["profile"]["reviewed_negative"] is True
        assert stored["profile"]["validated_at"]
        assert stored["attestation"] == {}
        assert result.new_profile["state"] == "none"
        assert result.new_profile["reviewed_negative"] is True
        assert result.new_attestation == {}

    def test_clears_prior_frozen_at(self, db_conn):
        insert_item(
            db_conn,
            id=101,
            status="refining-idea",
            db_mutation_profile='{"state":"none"}',
            db_compatibility_attestation='{"frozen_at":"2026-04-23T00:00:00Z"}',
        )
        amend(101, {"state": "none"}, reason="repair frozen state=none row", conn=db_conn)
        stored = _fetch_fields(db_conn, 101)
        assert FREEZE_FIELD not in stored["attestation"]
        assert stored["attestation"] == {}

    def test_rejects_attestation_fields_when_state_none(self, db_conn):
        insert_item(db_conn, id=102, status="refining-idea")
        with pytest.raises(DbClaimAmendmentError) as exc_info:
            amend(
                102,
                {"state": "none", "invariants": ["foo"]},
                reason="r",
                conn=db_conn,
            )
        assert "state='none'" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Happy path: state=declared
# ---------------------------------------------------------------------------


class TestStateDeclared:
    def test_pre_merge_safe_stamps_frozen_at(self, db_conn):
        insert_item(db_conn, id=200, status="refining-idea")
        result = amend(
            200,
            _declared_payload(),
            reason="declared governed schema change",
            conn=db_conn,
        )
        stored = _fetch_fields(db_conn, 200)
        assert stored["profile"]["state"] == "declared"
        assert stored["profile"]["model_name"] == "primary"
        assert stored["attestation"].get(FREEZE_FIELD)
        assert stored["attestation"]["invariants"] == [
            "items.due_date nullable after apply"
        ]
        # The ``authored`` fields landed on the attestation side.
        assert "due_date" not in stored["attestation"]
        assert result.new_attestation.get(FREEZE_FIELD)

    def test_pre_merge_safe_requires_all_authored_fields(self, db_conn):
        insert_item(db_conn, id=201, status="refining-idea")
        payload = _declared_payload()
        del payload["residual_risk_notes"]
        with pytest.raises(DbClaimAmendmentError) as exc_info:
            amend(201, payload, reason="r", conn=db_conn)
        msg = str(exc_info.value)
        assert "pre_merge_safe" in msg
        assert "residual_risk_notes" in msg
        # Stored fields unchanged (negative default).
        stored = _fetch_fields(db_conn, 201)
        assert stored["profile"] == {"state": "none"}

    def test_pre_merge_breaking_does_not_require_authored(self, db_conn):
        insert_item(db_conn, id=202, status="refining-idea")
        payload = {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": ["risky_rebuild"],
            "compatibility_class": "pre_merge_breaking",
            "migration_strategy": "additive_only",
        }
        amend(202, payload, reason="breaking change declared", conn=db_conn)
        stored = _fetch_fields(db_conn, 202)
        assert stored["profile"]["compatibility_class"] == "pre_merge_breaking"
        assert stored["attestation"].get(FREEZE_FIELD)

    def test_append_only_companions_carried_over(self, db_conn):
        prior_attestation = {
            FREEZE_FIELD: "2026-04-01T00:00:00Z",
            "pre_merge_readers_writers": [
                {"path": "x.py", "role": "reader"}
            ],
            "invariants": ["old invariant"],
            "rehearsal_commands": ["old cmd"],
            "residual_risk_notes": "old",
            "rehearsal_outcomes": [
                {"command": "pytest", "verdict": "pass",
                 "observed_at": "2026-04-02T00:00:00Z"}
            ],
            "class_escalations": [
                {"from": "pre_merge_safe", "to": "pre_merge_breaking",
                 "reason": "scanner hit",
                 "source": "scanner", "observed_at": "2026-04-02T00:00:00Z"}
            ],
        }
        insert_item(
            db_conn,
            id=203,
            status="refining-idea",
            db_mutation_profile='{"state":"declared","model_name":"primary",'
                                '"mutation_intent":"apply",'
                                '"migration_modules":["m"],'
                                '"compatibility_class":"pre_merge_safe",'
                                '"migration_strategy":"additive_only"}',
            db_compatibility_attestation=json.dumps(prior_attestation),
        )
        amend(
            203,
            _declared_payload(),
            reason="updated authored fields",
            conn=db_conn,
        )
        stored = _fetch_fields(db_conn, 203)
        assert len(stored["attestation"]["rehearsal_outcomes"]) == 1
        assert len(stored["attestation"]["class_escalations"]) == 1
        # New authored fields overwrote, companions preserved.
        assert stored["attestation"]["invariants"] == [
            "items.due_date nullable after apply"
        ]


# ---------------------------------------------------------------------------
# Atomicity
# ---------------------------------------------------------------------------


class TestAtomicity:
    def test_profile_validation_failure_leaves_both_fields_unchanged(self, db_conn):
        prior_profile = '{"state":"none"}'
        prior_attestation = '{"frozen_at":"2026-04-01T00:00:00Z"}'
        insert_item(
            db_conn,
            id=300,
            status="refining-idea",
            db_mutation_profile=prior_profile,
            db_compatibility_attestation=prior_attestation,
        )
        with pytest.raises(DbClaimAmendmentError):
            amend(
                300,
                {
                    "state": "declared",
                    "model_name": "primary",
                    # mutation_intent missing → profile validation fail
                    "migration_modules": ["m"],
                    "compatibility_class": "pre_merge_safe",
                },
                reason="r",
                conn=db_conn,
            )
        stored = _fetch_fields(db_conn, 300)
        assert stored["profile"] == {"state": "none"}
        assert stored["attestation"] == {"frozen_at": "2026-04-01T00:00:00Z"}

    def test_attestation_validation_failure_leaves_both_fields_unchanged(self, db_conn):
        insert_item(
            db_conn,
            id=301,
            status="refining-idea",
            db_mutation_profile='{"state":"none"}',
            db_compatibility_attestation='{}',
        )
        with pytest.raises(DbClaimAmendmentError):
            # bad role on reader/writer — attestation structural failure
            amend(
                301,
                _declared_payload(pre_merge_readers_writers=[
                    {"path": "x.py", "role": "bogus"}
                ]),
                reason="r",
                conn=db_conn,
            )
        stored = _fetch_fields(db_conn, 301)
        assert stored["profile"] == {"state": "none"}
        assert stored["attestation"] == {}


# ---------------------------------------------------------------------------
# Input discipline
# ---------------------------------------------------------------------------


class TestInputDiscipline:
    def test_rejects_reserved_frozen_at(self, db_conn):
        insert_item(db_conn, id=400, status="refining-idea")
        payload = _declared_payload()
        payload[FREEZE_FIELD] = "2026-04-23T00:00:00Z"
        with pytest.raises(DbClaimAmendmentError) as exc_info:
            amend(400, payload, reason="r", conn=db_conn)
        assert "reserved field" in str(exc_info.value)
        assert FREEZE_FIELD in str(exc_info.value)

    def test_rejects_unknown_keys(self, db_conn):
        insert_item(db_conn, id=401, status="refining-idea")
        payload = _declared_payload()
        payload["unexpected_key"] = "v"
        with pytest.raises(DbClaimAmendmentError) as exc_info:
            amend(401, payload, reason="r", conn=db_conn)
        assert "unknown keys" in str(exc_info.value)

    def test_rejects_empty_reason(self, db_conn):
        insert_item(db_conn, id=402, status="refining-idea")
        with pytest.raises(DbClaimAmendmentError):
            amend(402, {"state": "none"}, reason="", conn=db_conn)

    def test_rejects_missing_item(self, db_conn):
        missing_id = 9999
        with pytest.raises(DbClaimAmendmentError) as exc_info:
            amend(missing_id, {"state": "none"}, reason="r", conn=db_conn)
        assert f"YOK-{missing_id}" in str(exc_info.value)


# Upsert / event emission / read_claim coverage lives in
# test_db_claim_events_upsert.py.
