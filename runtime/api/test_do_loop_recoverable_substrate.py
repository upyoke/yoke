"""Focused regressions for recoverable advance-entry substrate behavior.

Reproduces concrete failure shapes from the ticket spec:

* AC-28 — re-entry shape: item already ``implementing``,
  routed advance hits a recoverable substrate failure before useful
  work began, ``/yoke do`` records the chain outcome instead of
  treating it as useful implementation progress.
* AC-33 — same re-entry shape but verifies the canonical holder lookup:
  another live session holds the work claim, and ``holder_session_for_item``
  returns the canonical claim facts (``claim_id``, holder
  ``session_id``, ``item_id``, ``claim_type``, ``claimed_at``) without
  any guessed raw SQL against ``items`` columns or
  ``work_claims.target_id``.

The tests exercise the helper surface in
:mod:`yoke_core.domain.sessions_handler_outcome` and
:mod:`yoke_core.domain.sessions_offer_revalidation` directly, so they
do not depend on the full HTTP/CLI offer path or scheduler fixtures.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from runtime.api.test_sessions import _create_schema, _register
from yoke_core.domain import db_backend
from yoke_core.domain.sessions import claim_work
from yoke_core.domain.sessions_handler_outcome import (
    OUTCOME_RECOVERABLE_SUBSTRATE,
    is_non_useful_step,
    record_recoverable_substrate_skip,
)
from yoke_core.domain.sessions_offer_revalidation import (
    classify_terminal_reason,
    holder_session_for_item,
)
from yoke_core.domain.sessions_queries_chain import read_chain_skip_memory
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def conn(tmp_path):
    """Authority-shaped session/item schema on a disposable Postgres test DB."""

    def apply_schema() -> None:
        c = db_backend.connect()
        try:
            _create_schema(c)
            c.commit()
        finally:
            c.close()

    with init_test_db(tmp_path, apply_schema=apply_schema) as db_path:
        c = connect_test_db(db_path)
        try:
            yield c
        finally:
            c.close()


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _seed_item(conn, *, item_id: int, status: str, project: str = "yoke") -> None:
    p = _p(conn)
    project_id = 1 if project == "yoke" else 2
    conn.execute(
        f"""INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, frozen)
           VALUES ({p}, {p}, 'issue', {p}, 'medium', {p}, {p},
                   '2026-05-01T00:00:00Z', '2026-05-06T00:00:00Z', 'user', 0)""",
        (item_id, f"Item {item_id}", status, project_id, item_id),
    )
    conn.commit()


class TestYok1599SubstrateReentry:
    """AC-28: routed advance hits recoverable substrate; chain outcome preserved."""

    def test_substrate_skip_records_no_useful_work_began(self, conn):
        # Reproduce the re-entry shape: item already ``implementing``, a
        # routed advance re-entry hit cwd drift / guard collision before
        # useful implementation work began. The chain skip memory entry
        # carries ``useful_work_began=False`` so /yoke do's Step C
        # treats this as a non-useful step.
        _seed_item(conn, item_id=1599, status="implementing")
        _register(conn, session_id="dispatcher-session")
        with patch("yoke_core.domain.events.emit_event"):
            entry = record_recoverable_substrate_skip(
                conn,
                session_id="dispatcher-session",
                chain_step=1,
                project="yoke",
                item_id=f"YOK-{1599}",
                routed_action="advance",
                failure_class="cwd_drift_after_scope_bind",
                remediation_owner=f"YOK-{1599}",
                current_status="implementing",
                useful_work_began=False,
            )
        assert entry["useful_work_began"] is False
        assert entry["failure_class"] == "cwd_drift_after_scope_bind"
        # Substrate failure outcome is in the no-bump set so
        # /yoke do does NOT count it as a useful step.
        assert is_non_useful_step(OUTCOME_RECOVERABLE_SUBSTRATE) is True

    def test_substrate_skip_dedups_same_item_in_chain(self, conn):
        # Chain skip memory carries the failed item so the next
        # offer does not immediately reselect the same item / action.
        _seed_item(conn, item_id=1599, status="implementing")
        _register(conn, session_id="chain-dedup-session")
        with patch("yoke_core.domain.events.emit_event"):
            record_recoverable_substrate_skip(
                conn,
                session_id="chain-dedup-session",
                chain_step=1,
                project="yoke",
                item_id=f"YOK-{1599}",
                routed_action="advance",
                failure_class="cwd_drift",
                remediation_owner=f"YOK-{1599}",
            )
        memory = read_chain_skip_memory(conn, "chain-dedup-session")
        assert len(memory) == 1
        # Offer revalidation walks the candidate set and skips items
        # whose id is present in skip memory; the dedup key is stored in
        # canonical bare-numeric form so a `YOK-N` scheduler candidate
        # matches via the read-side normalization.
        assert memory[0]["item_id"] == "1599"
        assert memory[0]["skip_reason"] == "recoverable_substrate"

    def test_substrate_terminal_reason_names_remediation_owner_in_trail(self, conn):
        # When all candidates reduce to substrate failures, the
        # terminal classification reads the dedicated terminal reason
        # AND the chain-skip memory entry carries ``remediation_owner``
        # so /yoke do's terminal summary can name it.
        _seed_item(conn, item_id=1599, status="implementing")
        _register(conn, session_id="terminal-session")
        with patch("yoke_core.domain.events.emit_event"):
            record_recoverable_substrate_skip(
                conn,
                session_id="terminal-session",
                chain_step=1,
                project="yoke",
                item_id=f"YOK-{1599}",
                routed_action="advance",
                failure_class="cwd_drift",
                remediation_owner=f"YOK-{1599}",
            )
        memory = read_chain_skip_memory(conn, "terminal-session")
        assert (
            classify_terminal_reason(memory)
            == "all_candidates_recoverable_substrate"
        )
        # remediation_owner is on each entry so the summary can
        # render the remediation owner without
        # hand-querying anything.
        assert memory[0]["remediation_owner"] == f"YOK-{1599}"


class TestYok1599HolderViaCanonicalSurface:
    """AC-33: ``holder_session_for_item`` returns canonical claim facts.

    The session that releases its own claims and observes another live
    session still holding the item must read the holder via the
    canonical typed ``work_claims`` schema (``target_kind='item'`` plus
    ``item_id``), not via guessed columns on ``items`` or
    ``work_claims.target_id``. AC-31 enumerates the canonical fact set
    and AC-34 ensures the same facts surface in skip events.
    """

    def test_holder_returns_canonical_claim_facts(self, conn):
        _seed_item(conn, item_id=1599, status="implementing")
        _register(conn, session_id="other-live-session")
        claim = claim_work(
            conn, session_id="other-live-session", item_id=f"YOK-{1599}"
        )
        ctx = holder_session_for_item(conn, f"YOK-{1599}")
        # The rendered context contains all five canonical facts.
        assert ctx["claim_id"] == claim["id"]
        assert ctx["holder_session_id"] == "other-live-session"
        assert ctx["item_id"] == 1599
        assert ctx["claim_type"] == "exclusive"
        assert ctx.get("claimed_at")
        assert "holder_unknown" not in ctx

    def test_holder_unknown_when_no_live_claim(self, conn):
        _seed_item(conn, item_id=1599, status="implementing")
        ctx = holder_session_for_item(conn, f"YOK-{1599}")
        # When the lookup genuinely fails, the rendered context
        # surfaces ``holder_unknown=True`` instead of inventing values.
        assert ctx == {"holder_unknown": True}

    def test_canonical_query_uses_typed_target_kind(self, conn):
        # The query must filter by typed ``target_kind='item'`` and
        # ``item_id`` (the canonical schema). Confirm by simulating a
        # row that would have matched the LEGACY ``target_id`` shape
        # but has the wrong ``target_kind`` — the canonical query
        # ignores it.
        _seed_item(conn, item_id=1599, status="implementing")
        _register(conn, session_id="legacy-shape-session")
        # Insert a process-target claim manually so the helper does
        # not pick it up by mistake.
        p = _p(conn)
        conn.execute(
            f"""INSERT INTO work_claims
               (session_id, target_kind, item_id, process_key,
                claim_type, claimed_at, last_heartbeat, conflict_group)
               VALUES ({p}, 'process', NULL, 'STRATEGIZE',
                       'exclusive', '2026-05-06T00:00:00Z',
                       '2026-05-06T00:00:00Z', 'STRATEGIZE')""",
            ("legacy-shape-session",),
        )
        conn.commit()
        ctx = holder_session_for_item(conn, f"YOK-{1599}")
        # No item-target claim exists, so the holder lookup honestly
        # reports holder_unknown rather than the process-target row.
        assert ctx == {"holder_unknown": True}
