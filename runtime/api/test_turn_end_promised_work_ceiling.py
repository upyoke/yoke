"""How many times one session may be held on one item, and how soon.

The ceiling and the cooldown are the only thing between a session that
keeps promising work and an unbounded reinjection loop. Both used to be
counted from retained ``ChainEndDeferred`` telemetry, so both reset when
those rows expired; they are read from the hold ledger the hold decision
itself writes.
"""

from __future__ import annotations

from datetime import timedelta

from runtime.api.turn_end_promised_work_test_support import _NOW, _Conn
from yoke_core.domain import turn_end_promised_work_gate as gate
from yoke_core.domain.session_recovery_facts import PROMISED_WORK_HOLDS_TABLE


def test_recent_hold_stays_capped_without_consulting_tool_use(monkeypatch) -> None:
    assert not hasattr(gate, "_completed_tool_use_since")
    held_at = _NOW - gate.REINJECTION_COOLDOWN + timedelta(seconds=1)
    monkeypatch.setattr(
        gate,
        "_reinjection_history",
        lambda conn, sid, item_id: (held_at.isoformat(), 1),
    )

    def _unexpected_tool_lookup(*args) -> bool:
        raise AssertionError("tool use must not affect the reinjection cooldown")

    monkeypatch.setattr(
        gate,
        "_completed_tool_use_since",
        _unexpected_tool_lookup,
        raising=False,
    )
    assert gate._at_reinjection_cap(_Conn(), "sess-1", 5, now=_NOW) is True


def test_expired_cooldown_reinjects_until_ceiling(monkeypatch) -> None:
    held_at = _NOW - gate.REINJECTION_COOLDOWN
    for hold_count in (1, gate.REINJECTION_CEILING - 1):
        monkeypatch.setattr(
            gate,
            "_reinjection_history",
            lambda conn, sid, item_id, count=hold_count: (
                held_at.isoformat(),
                count,
            ),
        )
        assert gate._at_reinjection_cap(_Conn(), "sess-1", 5, now=_NOW) is False


def test_ceiling_stays_capped_regardless_of_elapsed_time(monkeypatch) -> None:
    held_at = _NOW - (gate.REINJECTION_COOLDOWN * 10)
    monkeypatch.setattr(
        gate,
        "_reinjection_history",
        lambda conn, sid, item_id: (
            held_at.isoformat(),
            gate.REINJECTION_CEILING,
        ),
    )
    assert gate._at_reinjection_cap(_Conn(), "sess-1", 5, now=_NOW) is True


def test_ceiling_is_scoped_to_the_claim_item(monkeypatch) -> None:
    held_at = _NOW - gate.REINJECTION_COOLDOWN
    histories = {
        5: (held_at.isoformat(), gate.REINJECTION_CEILING),
        6: (held_at.isoformat(), 1),
    }
    monkeypatch.setattr(
        gate,
        "_reinjection_history",
        lambda conn, sid, item_id: histories[item_id],
    )
    assert gate._at_reinjection_cap(_Conn(), "sess-1", 5, now=_NOW) is True
    assert gate._at_reinjection_cap(_Conn(), "sess-1", 6, now=_NOW) is False


def test_reinjection_history_reads_the_hold_ledger_for_this_session_and_item(
    monkeypatch,
) -> None:
    """The ceiling counts recorded holds, never retained telemetry.

    Counting ``ChainEndDeferred`` events made both the ceiling and the
    cooldown reset when those rows expired, which re-armed an unbounded
    reinjection loop against the same item.
    """
    captured: dict[str, object] = {}

    class _Rows:
        def fetchone(self) -> dict[str, object]:
            return {"last_hold_at": _NOW.isoformat(), "hold_count": 2}

    class _HistoryConn:
        def execute(self, query: str, params: tuple[object, ...]) -> _Rows:
            captured["query"] = query
            captured["params"] = params
            return _Rows()

    monkeypatch.setattr(
        "yoke_core.domain.db_backend.connection_is_postgres",
        lambda conn: True,
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_recovery_facts.promised_work_holds_table_present",
        lambda conn: True,
    )
    assert gate._reinjection_history(_HistoryConn(), "sess-1", 6) == (
        _NOW.isoformat(),
        2,
    )
    query = str(captured["query"])
    assert PROMISED_WORK_HOLDS_TABLE in query
    assert "events" not in query
    assert captured["params"] == ("sess-1", 6)
