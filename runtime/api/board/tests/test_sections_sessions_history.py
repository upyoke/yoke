"""Active and closed BOARD.md rows share one bounded holdings path."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_contracts.board import sections_sessions


def test_active_and_closed_rows_render_the_same_holdings_shape(monkeypatch) -> None:
    active = (
        "active-1",
        "codex",
        "codex-cli",
        "model",
        "requested-model",
        "dash",
        "ALTMAN",
        "2026-08-28T12:00:00Z",
        "2026-08-28T12:05:00Z",
        "/tmp",
        1,
    )
    closed = (
        "closed-1",
        "codex",
        "codex-cli",
        "model",
        "requested-model",
        "dash",
        "ALTMAN",
        "2026-08-28T10:00:00Z",
        "2026-08-28T11:00:00Z",
        "/tmp",
        1,
        "2026-08-28T11:00:00Z",
    )

    def rows(_db, *, scope, active_only):
        assert scope == "all"
        return [active] if active_only else [closed]

    labels = {
        "active-1": ["YOK-8", "YOK-7", "and 3 more"],
        "closed-1": ["YOK-6", "and 9 more"],
    }
    monkeypatch.setattr(sections_sessions, "session_rows", rows)
    monkeypatch.setattr(
        sections_sessions,
        "session_holding_labels",
        lambda _db, session_id: labels[session_id],
    )
    monkeypatch.setattr(
        sections_sessions,
        "session_common_cells",
        lambda *_args: ["session", "project", "executor", "model"],
    )
    monkeypatch.setattr(
        sections_sessions, "session_lane_presentation", lambda *_args: None
    )
    monkeypatch.setattr(sections_sessions, "_format_session_age", lambda _value: "1h")

    rendered = sections_sessions.render_sessions_section(object())

    assert rendered.count("Claims") == 2
    assert "1h ago" in rendered
    for target in ("YOK-8", "YOK-7", "YOK-6", "and 3 more", "and 9 more"):
        assert target in rendered


def test_recent_future_ended_age_clamps_at_zero(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    closed = (
        "closed-1",
        "codex",
        "codex-cli",
        "model",
        "requested-model",
        "dash",
        "ALTMAN",
        (now - timedelta(minutes=1)).isoformat(),
        now.isoformat(),
        "/tmp",
        1,
        (now + timedelta(seconds=30)).isoformat(),
    )
    monkeypatch.setattr(
        sections_sessions,
        "session_rows",
        lambda _db, *, scope, active_only: [] if active_only else [closed],
    )
    monkeypatch.setattr(
        sections_sessions, "session_holding_labels", lambda *_args: []
    )
    monkeypatch.setattr(
        sections_sessions,
        "session_common_cells",
        lambda *_args: ["session", "project", "executor", "model"],
    )
    monkeypatch.setattr(
        sections_sessions, "session_lane_presentation", lambda *_args: None
    )

    rendered = sections_sessions.render_sessions_section(object())

    assert "0s ago" in rendered
    assert "-0s ago" not in rendered
