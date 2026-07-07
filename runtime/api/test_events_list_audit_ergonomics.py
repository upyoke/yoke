"""Tests for the ``events list`` audit-ergonomics fixes.

Covers the three changes in `runtime/api/domain/events_queries.py` and
its new siblings:

* ``--session`` accepted as an alias for ``--session-id``.
* ``--since`` / ``--until`` resolve relative phrases (``2 hours ago``)
  against an injected ``now`` and pass ISO timestamps unchanged.
* ``--failed-only`` and ``--friction-summary`` presets compose with
  the existing ``_build_where`` predicates.

Uses the existing ``db_path`` / ``_insert_event`` fixtures from
``events_crud_test_fixtures.py`` so the events table DDL matches
production.
"""
from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest

from yoke_core.domain import events_crud  # noqa: F401 — load order breaks circular import with events_queries
from yoke_core.domain import events_queries as eq
from yoke_core.domain.events_relative_time import parse_since
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.events_crud_test_fixtures import (  # noqa: F401
    _insert_event,
    db_path,
)


def _run_list(db_path: str, args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    rc = eq.cli_list(db_path, args, stdout=out, stderr=err)
    return rc, out.getvalue(), err.getvalue()


class TestSessionAlias:
    def test_session_alias_matches_session_id(self, db_path: str) -> None:
        _insert_event(db_path, event_id="e1", session_id="alpha")
        _insert_event(db_path, event_id="e2", session_id="beta")

        rc_alias, out_alias, _ = _run_list(db_path, ["--session", "alpha"])
        rc_canon, out_canon, _ = _run_list(db_path, ["--session-id", "alpha"])

        assert rc_alias == 0
        assert rc_canon == 0
        assert out_alias == out_canon
        assert "alpha" in out_alias
        assert "beta" not in out_alias


class TestRelativeSinceParsing:
    def test_iso_timestamp_passthrough(self) -> None:
        iso = "2026-05-01T00:00:00Z"
        assert parse_since(iso) == iso

    def test_relative_hours_resolves_against_injected_now(self) -> None:
        now = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
        resolved = parse_since("2 hours ago", now=now)
        assert resolved == "2026-05-19T10:00:00Z"

    def test_relative_days_resolves_against_injected_now(self) -> None:
        now = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
        assert parse_since("3 days ago", now=now) == "2026-05-16T12:00:00Z"

    def test_singular_unit_accepted(self) -> None:
        now = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
        assert parse_since("1 hour ago", now=now) == "2026-05-19T11:00:00Z"

    def test_case_insensitive(self) -> None:
        now = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
        assert parse_since("30 MINUTES AGO", now=now) == "2026-05-19T11:30:00Z"

    def test_unparseable_value_fails_closed(self) -> None:
        with pytest.raises(ValueError, match="unparseable"):
            parse_since("recently")

    def test_since_filter_uses_relative_anchor(
        self, db_path: str, monkeypatch
    ) -> None:
        now = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
        old = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        recent = (now - timedelta(minutes=30)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        _insert_event(db_path, event_id="old", session_id="s")
        _insert_event(db_path, event_id="recent", session_id="s")
        # Stamp deterministic timestamps so the relative window matches.
        conn = connect_test_db(db_path)
        conn.execute(
            "UPDATE events SET created_at=%s WHERE event_id='old'", (old,)
        )
        conn.execute(
            "UPDATE events SET created_at=%s WHERE event_id='recent'",
            (recent,),
        )
        conn.commit()
        conn.close()

        from yoke_core.domain import events_relative_time as ert

        monkeypatch.setattr(
            ert, "datetime", _FrozenDatetime(now), raising=True
        )
        rc, out, _ = _run_list(db_path, ["--since", "2 hours ago"])
        assert rc == 0
        assert "recent" in out
        assert "old" not in out


class _FrozenDatetime:
    """Patch shim for ``datetime.now(timezone.utc)`` used in parse_since."""

    def __init__(self, anchor: datetime) -> None:
        self._anchor = anchor

    def now(self, tz):  # noqa: D401 - matches datetime.now signature
        return self._anchor

    @classmethod
    def fromisoformat(cls, value: str):  # pragma: no cover - parity
        return datetime.fromisoformat(value)


class TestFailedOnlyPreset:
    def test_filters_to_failed_class(self, db_path: str) -> None:
        _insert_event(
            db_path, event_id="evt-ok-1", session_id="s", event_outcome="ok"
        )
        _insert_event(
            db_path, event_id="evt-fail-1", session_id="s", event_outcome="failed"
        )
        _insert_event(
            db_path, event_id="evt-deny-1", session_id="s", event_outcome="denied"
        )
        rc, out, _ = _run_list(db_path, ["--failed-only"])
        assert rc == 0
        assert "evt-fail-1" in out
        assert "evt-deny-1" in out
        assert "evt-ok-1" not in out

    def test_composes_with_session_filter(self, db_path: str) -> None:
        _insert_event(
            db_path, event_id="evt-alpha-fail",
            session_id="alpha", event_outcome="failed",
        )
        _insert_event(
            db_path, event_id="evt-beta-fail",
            session_id="beta", event_outcome="failed",
        )
        _insert_event(
            db_path, event_id="evt-alpha-ok",
            session_id="alpha", event_outcome="ok",
        )
        rc, out, _ = _run_list(
            db_path, ["--failed-only", "--session", "alpha"]
        )
        assert rc == 0
        assert "evt-alpha-fail" in out
        assert "evt-beta-fail" not in out  # filtered by session
        assert "evt-alpha-ok" not in out  # filtered by outcome


class TestFrictionSummary:
    def test_aggregates_by_session(self, db_path: str) -> None:
        _insert_event(
            db_path, event_id="a1", session_id="alpha", event_outcome="failed"
        )
        _insert_event(
            db_path, event_id="a2", session_id="alpha", event_outcome="denied"
        )
        _insert_event(
            db_path, event_id="a3", session_id="alpha", event_outcome="failed"
        )
        _insert_event(
            db_path, event_id="beta-timeout", session_id="beta", event_outcome="timeout"
        )
        rc, out, _ = _run_list(db_path, ["--friction-summary"])
        assert rc == 0
        lines = out.strip().split("\n")
        # Header + alpha + beta
        assert lines[0].startswith("session_id|failed|denied")
        assert any(line.startswith("alpha|2|1|0|0|3") for line in lines)
        assert any(line.startswith("beta|0|0|0|1|1") for line in lines)


class TestExistingRegressions:
    def test_unparseable_since_returns_exit_2(self, db_path: str) -> None:
        rc, _, err = _run_list(db_path, ["--since", "recently"])
        assert rc == 2
        assert "unparseable" in err

    def test_unknown_flag_still_rejected(self, db_path: str) -> None:
        rc, _, err = _run_list(db_path, ["--bogus", "value"])
        assert rc == 2
        assert "unknown filter flag" in err
