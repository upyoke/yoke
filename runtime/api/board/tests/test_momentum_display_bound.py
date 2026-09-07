"""The bound both momentum renderers treat as full height.

The board and the Overview each assemble their own series — the board
holds one project, the web view sums the projects in scope — so each
computes the bound in its own runtime. These cases come from the shared
fixture the JavaScript suite reads, which is what keeps the two
implementations from drifting apart.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.board.momentum_series import display_bound, display_fraction
from yoke_contracts.board.widgets_activity import _build_sparkline

_FIXTURE = Path(__file__).resolve().parents[2] / "momentum_display_bound_fixture.json"


def _cases() -> list[dict]:
    return json.loads(_FIXTURE.read_text())["cases"]


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["name"])
def test_display_bound_matches_the_shared_fixture(case: dict) -> None:
    assert display_bound(case["values"]) == pytest.approx(case["bound"])


def test_a_day_at_or_beyond_the_bound_is_full_height() -> None:
    bound = display_bound([1] * 39 + [1000])
    assert display_fraction(1000, bound) == 1.0
    assert display_fraction(bound, bound) == 1.0


def test_an_outlier_no_longer_flattens_the_days_around_it() -> None:
    # One import-sized day against ordinary ones. Scaling by the raw
    # maximum left every ordinary day on the first level; the bound lets
    # them spread across the range while the outlier still reads full.
    values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100] * 4 + [100_000]
    rendered = _build_sparkline(values)

    assert rendered[-1] == "█", "the outlier still draws full height"
    assert len(set(rendered)) > 3, (
        f"ordinary days should spread across levels, got {sorted(set(rendered))}"
    )


def test_strategy_reads_saved_revisions_rather_than_expiring_telemetry() -> None:
    # The measure has to survive event retention, so it must not name the
    # events table at all.
    from yoke_contracts.board.momentum_series import _strategy_query

    sql, params = _strategy_query([1], 120)
    assert "strategy_doc_revisions" in sql
    assert "FROM events" not in sql
    assert "new_bytes" not in sql and "old_bytes" not in sql
    assert params == (1,)


def test_strategy_measures_adjacent_saved_revision_sizes() -> None:
    from yoke_contracts.board.momentum_series import _strategy_query

    sql, _ = _strategy_query([1], 120)
    # Adjacent sizes, partitioned per document, ordered by revision.
    assert "LAG(byte_length) OVER (" in sql
    assert "PARTITION BY project_id, slug ORDER BY revision" in sql
    assert "ABS(byte_length - COALESCE(previous_byte_length, 0))" in sql
    # A first saved revision that is not revision 1 has no knowable
    # baseline, so it is excluded rather than counted as whole-size.
    assert "WHERE previous_byte_length IS NOT NULL OR revision = 1" in sql


def test_strategy_windows_the_whole_history_before_cutting_off_days() -> None:
    # Applying the day cutoff inside the window would make whichever
    # revision opens the window look like its document's baseline.
    from yoke_contracts.board.momentum_series import _strategy_query

    sql, _ = _strategy_query([1], 120)
    window_end = sql.index(") adjacent")
    assert "to_char" not in sql[:window_end], (
        "the day cutoff must not filter the rows the window reads"
    )
    assert "to_char" in sql[window_end:]


def test_strategy_serves_a_payload_recorded_before_this_measure() -> None:
    # The board renders from a payload recorded server-side, so between this
    # build merging and the server shipping it the query is absent. The only
    # strategy figure such a payload holds is the expiring events total this
    # measure replaced, so the series is empty rather than wrong, and the
    # board still renders.
    from yoke_contracts.board.momentum_series import (
        _strategy_query,
        strategy_bytes_by_day,
    )

    project_ids = [1]
    revisions_sql, _ = _strategy_query(project_ids, 120)

    class _PayloadWithoutTheMeasure:
        def has_query(self, sql: str, params=None) -> bool:
            return sql != revisions_sql

        def query(self, sql: str, params=None):
            raise AssertionError("must not issue an unrecorded query")

    assert strategy_bytes_by_day(
        _PayloadWithoutTheMeasure(), project_ids, days=120,
    ) == {}


def test_strategy_serves_a_payload_that_carries_the_measure() -> None:
    from yoke_contracts.board.momentum_series import (
        _strategy_query,
        strategy_bytes_by_day,
    )

    project_ids = [1]
    revisions_sql, _ = _strategy_query(project_ids, 120)

    class _PayloadWithTheMeasure:
        def has_query(self, sql: str, params=None) -> bool:
            return True

        def query(self, sql: str, params=None):
            assert sql == revisions_sql
            return [("2026-07-05", 17)]

    assert strategy_bytes_by_day(
        _PayloadWithTheMeasure(), project_ids, days=120,
    ) == {"2026-07-05": 17}


def test_an_empty_day_stays_on_the_baseline_glyph() -> None:
    rendered = _build_sparkline([0, 5, 0, 9])
    assert rendered[0] == "▁"
    assert rendered[2] == "▁"
    assert rendered[1] != "▁"
