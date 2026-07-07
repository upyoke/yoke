"""Lifecycle-level reviewed-negative-claim regression for the prose-vs-claim gate.

Sibling to ``test_backlog_updates_helpers.py`` which holds the unit-level
profile/joint-gate/prose-mismatch coverage. The helper_db fixture is
duplicated here rather than promoted to a directory-wide conftest because
it is scoped to the gate helpers under test.

The reviewed-negative signal lives ON the ``db_mutation_profile`` JSON
(``reviewed_negative: true`` + ``validated_at``, stamped by the
``db_claim.amend`` workflow) — the gate consults the profile, not event
history.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.backlog_updates_helpers import (
    _run_db_mutation_gate,
    _run_prose_vs_claim_check,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.backlog import (
    SCHEMA_DDL,
    insert_item,
)


_EXTRA_DDL = """
CREATE TABLE IF NOT EXISTS project_capabilities (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    type TEXT NOT NULL,

    settings TEXT DEFAULT '{}',
    verified_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, type)
);

CREATE TABLE IF NOT EXISTS migration_audit (
    id INTEGER PRIMARY KEY,
    migration_name TEXT NOT NULL,
    status TEXT,
    state TEXT,
    model_name TEXT,
    project_id INTEGER
);
"""


@pytest.fixture
def helper_db(tmp_path: Path):
    """File-backed DB so ``_run_db_mutation_gate`` can resolve ``db_path``."""
    db_file = tmp_path / "yoke.db"
    conn = connect_test_db(str(db_file))
    execute_schema_script(conn, SCHEMA_DDL)
    execute_schema_script(conn, _EXTRA_DDL)
    conn.commit()
    yield conn, str(db_file)
    conn.close()


def _profile(
    *,
    state: str = "none",
    reviewed_negative: bool | None = None,
    validated_at: str | None = None,
) -> str:
    payload: dict = {"state": state}
    if reviewed_negative is not None:
        payload["reviewed_negative"] = reviewed_negative
    if validated_at is not None:
        payload["validated_at"] = validated_at
    return json.dumps(payload, sort_keys=True)


class TestProseVsClaimReviewedNegativeClaim:
    """Lifecycle-level regression for the reviewed-negative-claim escape.

    Reproduces the pattern: meta-tickets about DB governance cite
    ``ALTER TABLE`` / ``ADD COLUMN`` / ``migration_audit`` in plain prose
    and must still advance once the ``db_claim.amend`` workflow has stamped
    the reviewed-negative attestation onto the profile JSON.
    """

    def test_raw_prose_with_attestation_unblocks_gate(self, helper_db) -> None:
        conn, db_path = helper_db
        item_id = 70
        insert_item(
            conn, id=item_id, status="refining-idea",
            spec=(
                "This ticket changes the prose-vs-claim gate so "
                "meta-tickets can discuss ALTER TABLE, ADD COLUMN, "
                "DROP COLUMN, and migration_audit without being blocked."
            ),
            db_mutation_profile=_profile(
                reviewed_negative=True,
                validated_at="2026-04-24T16:35:36Z",
            ),
        )
        conn.commit()

        assert (
            _run_prose_vs_claim_check(item_id=item_id, db_path=db_path)
            is None
        )
        assert (
            _run_db_mutation_gate(
                item_id=item_id,
                target_status="refined-idea",
                db_path=db_path,
            )
            is None
        )

    def test_raw_prose_without_attestation_still_blocks(
        self, helper_db
    ) -> None:
        conn, db_path = helper_db
        item_id = 71
        insert_item(
            conn, id=item_id, status="refining-idea",
            spec=(
                "The implementation will ALTER TABLE items and "
                "ADD COLUMN due_date on the authoritative DB."
            ),
            db_mutation_profile=_profile(),
        )
        conn.commit()

        outcome = _run_prose_vs_claim_check(
            item_id=item_id, db_path=db_path,
        )
        assert outcome is not None
        assert outcome["error_code"] == "GATE_DB_CLAIM_PROSE_MISMATCH"
        assert "db-claim-amend" in outcome["error"]
        assert "ALTER TABLE" in outcome["error"]

    def test_explicit_false_attestation_still_blocks(self, helper_db) -> None:
        """``reviewed_negative: false`` (e.g. a stamp the amend workflow
        refused on validation failure) is not a reviewed-none signal even
        with a ``validated_at`` timestamp present."""
        conn, db_path = helper_db
        item_id = 72
        insert_item(
            conn, id=item_id, status="refining-idea",
            spec="Performs ALTER TABLE items during apply.",
            db_mutation_profile=_profile(
                reviewed_negative=False,
                validated_at="2026-04-24T16:35:36Z",
            ),
        )
        conn.commit()
        outcome = _run_prose_vs_claim_check(
            item_id=item_id, db_path=db_path,
        )
        assert outcome is not None
        assert outcome["error_code"] == "GATE_DB_CLAIM_PROSE_MISMATCH"

    def test_attestation_is_a_none_state_concept(self, helper_db) -> None:
        """A declared claim passes the prose check via claim consistency —
        the attestation keys are irrelevant outside ``state="none"``.
        (``is_reviewed_negative`` unit coverage lives in
        ``test_db_claim_prose_check_attestation.py``.)"""
        conn, db_path = helper_db
        item_id = 73
        insert_item(
            conn, id=item_id, status="refining-idea",
            spec="Performs ALTER TABLE items during apply.",
            db_mutation_profile=json.dumps(
                {
                    "state": "declared",
                    "reviewed_negative": True,
                    "mutation_intent": "apply",
                },
                sort_keys=True,
            ),
        )
        conn.commit()
        assert (
            _run_prose_vs_claim_check(item_id=item_id, db_path=db_path)
            is None
        )
