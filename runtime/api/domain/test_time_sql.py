"""Tests for :mod:`yoke_core.domain.time_sql`.

The helper never executes SQL; it returns Postgres fragments that are
interpolated into larger query strings. These tests pin the emitted fragment
shape.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.time_sql import now_sql


class TestArgumentValidation:
    def test_multiple_fixed_offsets_rejected(self) -> None:
        with pytest.raises(ValueError, match="at most one of"):
            now_sql(offset_days=-30, offset_hours=-1)

    def test_fixed_and_modifier_rejected(self) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            now_sql(offset_days=-30, offset_modifier="%s")

    def test_all_three_fixed_offsets_rejected(self) -> None:
        with pytest.raises(ValueError, match="at most one of"):
            now_sql(offset_days=-1, offset_hours=-1, offset_minutes=-1)


class TestPostgresFragments:
    def test_bare_now(self) -> None:
        assert now_sql() == (
            "to_char((now() AT TIME ZONE 'utc'), 'YYYY-MM-DD HH24:MI:SS')"
        )

    def test_localtime_only(self) -> None:
        assert now_sql(localtime=True) == (
            "to_char(LOCALTIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')"
        )

    def test_negative_days(self) -> None:
        assert now_sql(offset_days=-30) == (
            "to_char((now() AT TIME ZONE 'utc') + make_interval(days => -30), "
            "'YYYY-MM-DD HH24:MI:SS')"
        )

    def test_positive_days(self) -> None:
        assert now_sql(offset_days=7) == (
            "to_char((now() AT TIME ZONE 'utc') + make_interval(days => 7), "
            "'YYYY-MM-DD HH24:MI:SS')"
        )

    def test_zero_days(self) -> None:
        assert now_sql(offset_days=0) == (
            "to_char((now() AT TIME ZONE 'utc') + make_interval(days => 0), "
            "'YYYY-MM-DD HH24:MI:SS')"
        )

    def test_negative_hours(self) -> None:
        assert now_sql(offset_hours=-24) == (
            "to_char((now() AT TIME ZONE 'utc') + make_interval(hours => -24), "
            "'YYYY-MM-DD HH24:MI:SS')"
        )

    def test_negative_minutes(self) -> None:
        assert now_sql(offset_minutes=-15) == (
            "to_char((now() AT TIME ZONE 'utc') + make_interval(mins => -15), "
            "'YYYY-MM-DD HH24:MI:SS')"
        )

    def test_placeholder_only(self) -> None:
        assert now_sql(offset_modifier="%s") == (
            "to_char((now() AT TIME ZONE 'utc') + (%s)::interval, "
            "'YYYY-MM-DD HH24:MI:SS')"
        )

    def test_placeholder_concat_minutes(self) -> None:
        assert now_sql(offset_modifier="%s || ' minutes'") == (
            "to_char((now() AT TIME ZONE 'utc') + (%s || ' minutes')::interval, "
            "'YYYY-MM-DD HH24:MI:SS')"
        )

    def test_raw_literal_fragment(self) -> None:
        assert now_sql(offset_modifier="'-45 seconds'") == (
            "to_char((now() AT TIME ZONE 'utc') + ('-45 seconds')::interval, "
            "'YYYY-MM-DD HH24:MI:SS')"
        )

    def test_localtime_plus_fixed_window(self) -> None:
        assert now_sql(offset_days=-7, localtime=True) == (
            "to_char(LOCALTIMESTAMP + make_interval(days => -7), "
            "'YYYY-MM-DD HH24:MI:SS')"
        )

    def test_localtime_plus_placeholder(self) -> None:
        assert now_sql(offset_modifier="%s", localtime=True) == (
            "to_char(LOCALTIMESTAMP + (%s)::interval, 'YYYY-MM-DD HH24:MI:SS')"
        )
