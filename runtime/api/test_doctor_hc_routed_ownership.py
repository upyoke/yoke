"""Tests for the routed-ownership doctor health checks."""

from __future__ import annotations

from runtime.api.fixtures import pg_testdb
from yoke_core.engines.doctor_hc_routed_ownership import (
    hc_offer_envelope_clobber_lost_chain,
    hc_routed_ownership_live_frame_no_defense,
    hc_routed_ownership_non_terminal_release_still_schedulable,
)

# Fixture + seed helpers live in a sibling module so this test file stays
# within the AGENTS.md file budget. ``conn`` is the backend-aware per-test DB
# fixture; the ``_insert_*`` / ``_run`` helpers seed the minimal table set on
# its disposable Postgres authority.
from runtime.api.test_doctor_hc_routed_ownership_helpers import (  # noqa: F401
    conn,
    _insert_item,
    _insert_released_claim,
    _insert_session,
    _iso,
    _run,
)


class TestLiveFrameNoDefense:
    def test_pass_on_clean_db(self, conn) -> None:
        rec = _run(hc_routed_ownership_live_frame_no_defense, conn)
        assert rec.results[-1].result == "PASS"

    def test_skip_when_tables_missing(self) -> None:
        # Empty disposable database: no tables at all, so the HC's
        # required-tables probe must self-skip.
        name = pg_testdb.create_test_database()
        c = pg_testdb.connect_test_database(name)
        try:
            rec = _run(hc_routed_ownership_live_frame_no_defense, c)
            assert rec.results[-1].result == "PASS"
            assert "skipping" in rec.results[-1].detail.lower()
        finally:
            c.close()
            pg_testdb.drop_test_database(name)

    def test_pass_when_defense_covers_audited_session(self, conn) -> None:
        """AC-4 proof: HC iterates the same session whose release the
        defense must name; requesting_session_id=None must NOT filter."""
        _insert_session(conn, "owner-A", heartbeat_age_s=5)
        _insert_released_claim(
            conn, "owner-A", 4242, released_age_s=5,
            release_reason="released",
            release_reason_intent="readiness-check-blocked",
        )
        rec = _run(hc_routed_ownership_live_frame_no_defense, conn)
        assert rec.results[-1].result == "PASS"

    def test_warn_when_defense_window_expired(self, conn) -> None:
        # Released long ago: oracle does not defend (outside window),
        # but the audit shows the session is still live and the release
        # intent on the claim row was non-terminal.
        far_age = 2 * 60 * 60  # 2 hours; well beyond default 300s window
        _insert_session(conn, "owner-B", heartbeat_age_s=5)
        _insert_released_claim(
            conn, "owner-B", 7777, released_age_s=far_age,
            release_reason_intent="readiness-check-blocked",
        )
        rec = _run(hc_routed_ownership_live_frame_no_defense, conn)
        result = rec.results[-1]
        assert result.result == "WARN"
        assert "YOK-7777" in result.detail
        assert "owner-B" in result.detail


class TestStillSchedulable:
    def test_pass_on_clean_db(self, conn) -> None:
        rec = _run(
            hc_routed_ownership_non_terminal_release_still_schedulable, conn,
        )
        assert rec.results[-1].result == "PASS"

    def test_skip_when_items_table_missing(self, conn) -> None:
        conn.execute("DROP TABLE items")
        conn.commit()
        rec = _run(
            hc_routed_ownership_non_terminal_release_still_schedulable, conn,
        )
        assert rec.results[-1].result == "PASS"
        assert "skipping" in rec.results[-1].detail.lower()

    def test_warn_when_routable_status_under_non_terminal_release(
        self, conn,
    ) -> None:
        _insert_session(conn, "owner-C", heartbeat_age_s=5)
        _insert_released_claim(
            conn, "owner-C", 9001, released_age_s=7200,
            release_reason_intent="readiness-check-blocked",
        )
        _insert_item(conn, 9001, "refined-idea")
        rec = _run(
            hc_routed_ownership_non_terminal_release_still_schedulable, conn,
        )
        result = rec.results[-1]
        assert result.result == "WARN"
        assert "YOK-9001" in result.detail
        assert "owner-C" in result.detail

    def test_pass_when_routable_status_is_defended(self, conn) -> None:
        _insert_session(conn, "owner-covered", heartbeat_age_s=5)
        _insert_released_claim(
            conn, "owner-covered", 9003, released_age_s=5,
            release_reason_intent="readiness-check-blocked",
        )
        _insert_item(conn, 9003, "refined-idea")
        rec = _run(
            hc_routed_ownership_non_terminal_release_still_schedulable, conn,
        )
        assert rec.results[-1].result == "PASS"

    def test_pass_when_item_status_is_terminal(self, conn) -> None:
        _insert_session(conn, "owner-D", heartbeat_age_s=5)
        _insert_released_claim(
            conn, "owner-D", 9002, released_age_s=5,
            release_reason_intent="readiness-check-blocked",
        )
        _insert_item(conn, 9002, "done")
        rec = _run(
            hc_routed_ownership_non_terminal_release_still_schedulable, conn,
        )
        assert rec.results[-1].result == "PASS"


class TestOfferEnvelopeClobber:
    def test_pass_on_clean_db(self, conn) -> None:
        rec = _run(hc_offer_envelope_clobber_lost_chain, conn)
        assert rec.results[-1].result == "PASS"

    def test_skip_when_tables_missing(self) -> None:
        # Empty disposable database: no tables at all, so the HC's
        # required-tables probe must self-skip.
        name = pg_testdb.create_test_database()
        c = pg_testdb.connect_test_database(name)
        try:
            rec = _run(hc_offer_envelope_clobber_lost_chain, c)
            assert rec.results[-1].result == "PASS"
            assert "skipping" in rec.results[-1].detail.lower()
        finally:
            c.close()
            pg_testdb.drop_test_database(name)

    def test_pass_when_checkpoint_preserved(self, conn) -> None:
        """Session reached step 3 and the current envelope still carries
        step 3 — chain state and envelope agree."""
        _insert_session(
            conn, "sess-good", heartbeat_age_s=5,
            offer_envelope={"chain_checkpoint": {"step": 3}},
            last_chain_step=3,
            last_checkpoint_at=_iso(-120),
        )
        rec = _run(hc_offer_envelope_clobber_lost_chain, conn)
        assert rec.results[-1].result == "PASS"

    def test_warn_when_envelope_lost_checkpoint(self, conn) -> None:
        """A later offer replaced the envelope wholesale: chain state says
        step 5, the live envelope carries no chain_checkpoint at all."""
        _insert_session(
            conn, "sess-clob", heartbeat_age_s=5, offer_envelope={"step": 7},
            last_chain_step=5,
            last_checkpoint_at=_iso(-180),
        )
        rec = _run(hc_offer_envelope_clobber_lost_chain, conn)
        result = rec.results[-1]
        assert result.result == "WARN"
        assert "sess-clob" in result.detail
        assert "max_step=5" in result.detail

    def test_pass_when_no_chain_state_recorded(self, conn) -> None:
        """NULL chain state means no checkpoints ever — nothing to lose."""
        _insert_session(
            conn, "sess-fresh", heartbeat_age_s=5, offer_envelope={"step": 1},
        )
        rec = _run(hc_offer_envelope_clobber_lost_chain, conn)
        assert rec.results[-1].result == "PASS"
