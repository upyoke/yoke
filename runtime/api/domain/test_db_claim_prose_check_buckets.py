"""Bucket-fixture coverage for the prose-vs-claim detector.

Companion to ``test_db_claim_prose_check.py``. Houses the
real-mutation-vs-meta-ticket prose fixtures so the parent test file
stays under the file-line gate after this addition.

These tests exercise the existing detector — no new logic, just two
representative prose strings that the three-bucket discipline in
``.agents/skills/yoke/idea/body-and-sync.md`` step 8b refers to:

* a real governed mutation prose example (schema change, trigger, and
  ``migration_audit`` writes — Bucket 1 or 2 in skill prose), and
* a meta-ticket prose example that cites ``ALTER TABLE`` / ``ADD COLUMN``
  / ``governed DB`` only because it discusses gate vocabulary (Bucket 3).

The detector itself does not classify intent — both fixtures fire
triggers. The bucket distinction is what the operator records via the
``db_claim.amend`` workflow (which stamps the reviewed-negative
attestation onto the stored profile), validated downstream by the
gate-honors-reviewed-none logic.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.db_claim_prose_check import check_item, detect_triggers
from yoke_core.domain.db_claim_prose_check_test_helpers import (
    _stamp_reviewed_none_profile,
)
from runtime.api.fixtures.backlog import insert_item


@pytest.fixture
def db_conn(test_db):
    """Postgres-backed connection with the full Yoke schema (canonical test_db)."""
    return test_db


_REAL_GOVERNED_MUTATION_PROSE = """\
Add a SQLite AFTER UPDATE trigger on qa_runs that writes a row into
migration_audit when verdict transitions away from pending. This is a
schema change against the governed authoritative DB; the implementation
ships a one-shot migration module under runtime/api/domain/migrations/
that performs the live apply through the governed runner.
"""


_META_TICKET_PROSE = """\
Tighten the prose-vs-claim gate so meta-tickets that cite ALTER TABLE,
ADD COLUMN, or governed DB only when describing the gate vocabulary they
are hardening do not get blocked. The change edits skill prose and the
prose-trigger composition; no schema change, no governed authoritative
DB mutation, no migration_audit row written by this ticket.
"""


class TestRealMutationVsMetaTicketProse:
    """Real governed mutation prose fixture and meta-ticket prose
    fixture. Both exercise the existing prose-trigger detector so the
    bucket-distinction documentation in body-and-sync.md step 8b is
    grounded in real classifier output."""

    def test_real_governed_mutation_prose_fires_triggers(self):
        labels = [t[0] for t in detect_triggers(_REAL_GOVERNED_MUTATION_PROSE)]
        assert "migration_audit" in labels, labels
        assert "governed DB" in labels or "authoritative DB" in labels, labels

    def test_real_governed_mutation_prose_blocks_with_state_none(self, db_conn):
        item_id = 1601
        insert_item(
            db_conn,
            id=item_id,
            status="idea",
            spec=_REAL_GOVERNED_MUTATION_PROSE,
            db_mutation_profile='{"state":"none"}',
        )
        outcome = check_item(item_id, conn=db_conn)
        # Real governed mutation with state="none" must block — this is
        # exactly the failure mode the three-bucket discipline prevents.
        # Bucket 2 (real-mutation-blocker) intentionally leaves the
        # schema default in place so this gate fires on the next advance.
        assert outcome.blocks is True
        assert outcome.has_declared_claim is False

    def test_meta_ticket_prose_fires_triggers(self):
        labels = [t[0] for t in detect_triggers(_META_TICKET_PROSE)]
        # Meta-ticket prose still trips the detector because it names DB
        # vocabulary verbatim. Bucket 3 reviewed-none is the recorded
        # signal that distinguishes intentional discussion from silent
        # deferral; the detector itself does not classify intent.
        assert "ALTER TABLE" in labels, labels
        assert "ADD COLUMN" in labels or "add column" in labels, labels
        assert "governed DB" in labels, labels

    def test_meta_ticket_prose_clears_with_canonical_reviewed_none(
        self, db_conn
    ):
        """Meta-ticket prose plus a canonical reviewed-none amendment
        clears the gate. The amendment workflow stamps the
        reviewed-negative attestation onto the stored profile — the
        bucket-3 signal documented in body-and-sync.md step 8b; the gate
        honors the stamped attestation regardless of reason text, so
        this test asserts the cleared verdict, not the reason-text
        contents."""
        item_id = 1602
        insert_item(
            db_conn,
            id=item_id,
            status="idea",
            spec=_META_TICKET_PROSE,
            db_mutation_profile='{"state":"none"}',
        )
        _stamp_reviewed_none_profile(db_conn, item_id=item_id)
        outcome = check_item(item_id, conn=db_conn)
        assert outcome.reviewed_negative_claim_detected is True
        assert outcome.blocks is False
