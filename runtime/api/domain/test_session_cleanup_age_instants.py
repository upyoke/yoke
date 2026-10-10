"""Cleanup reports floor Native elapsed ages without float precision loss."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from yoke_core.domain import sessions_cleanup as cleanup, time_parse
from yoke_contracts.timestamps import format_instant


@pytest.mark.parametrize("year", [1, 1000, 1969, 2025])
@pytest.mark.parametrize("microseconds", [-1, 0, 1])
@pytest.mark.parametrize("offset", [0, 330, -240])
def test_held_session_report_preserves_exact_whole_minutes(
    monkeypatch, year, microseconds, offset
):
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    activity = (
        datetime(year, 1, 2, tzinfo=timezone.utc) + timedelta(microseconds=microseconds)
    ).astimezone(timezone(timedelta(minutes=offset)))

    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    if hasattr(cleanup, "datetime"):
        monkeypatch.setattr(cleanup, "datetime", FrozenClock)
    monkeypatch.setattr(time_parse, "utc_now", lambda: now)
    monkeypatch.setattr(cleanup, "_now_iso", lambda: format_instant(now))
    monkeypatch.setattr(cleanup, "_schema_get_columns", lambda *_: {"executor"})
    monkeypatch.setattr(cleanup, "active_holding_sessions", lambda *_: {"held"})
    monkeypatch.setattr(cleanup, "active_work_claim_sessions", lambda *_: {"held"})
    monkeypatch.setattr(cleanup, "activity_is_stale", lambda *_a, **_k: True)
    monkeypatch.setattr(
        cleanup,
        "read_activity_signals",
        lambda *_a, **_k: SimpleNamespace(activity_at=activity, in_flight=False),
    )
    monkeypatch.setattr(cleanup._sa, "_emit_session_event", lambda *_a, **_k: None)
    row = {"session_id": "held", "executor": "codex", "offered_at": activity}

    def read_only(query, params):
        assert query.startswith("SELECT session_id, offered_at, executor")
        return SimpleNamespace(fetchall=lambda: [row])

    result = cleanup.clean_stale_harness_sessions(
        SimpleNamespace(execute=read_only), project_ids=[1]
    )
    (entry,) = result["skipped_between_turns"]
    assert entry["reason"] == "active_work_claim"
    assert entry["activity_at"] is activity
    assert entry["stale_minutes"] == (now - activity) // timedelta(minutes=1)
    assert result["total_reclaimed"] == 0
