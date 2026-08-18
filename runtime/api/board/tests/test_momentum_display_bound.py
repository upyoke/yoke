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


def test_strategy_serves_a_payload_recorded_before_the_net_change_measure() -> None:
    # The board renders from a payload recorded server-side, so between this
    # build merging and the server shipping it the newer query is absent.
    # Falling back to the whole-size total the payload does hold keeps the
    # board rendering instead of aborting the rebuild.
    from yoke_contracts.board.momentum_series import (
        _strategy_query,
        strategy_bytes_by_day,
    )

    project_ids = [1]
    net_change_sql, params = _strategy_query(project_ids, 120, net_change=True)
    whole_size_sql, _ = _strategy_query(project_ids, 120, net_change=False)
    assert net_change_sql != whole_size_sql

    class _PayloadWithoutNetChange:
        def __init__(self) -> None:
            self.served: list[str] = []

        def has_query(self, sql: str, params=None) -> bool:
            return sql == whole_size_sql

        def query(self, sql: str, params=None):
            self.served.append(sql)
            assert sql == whole_size_sql, "must not issue an unrecorded query"
            return [("2026-07-05", 4200)]

    db = _PayloadWithoutNetChange()
    assert strategy_bytes_by_day(db, project_ids, days=120) == {"2026-07-05": 4200}
    assert db.served == [whole_size_sql]


def test_strategy_prefers_the_net_change_measure_when_the_payload_has_it() -> None:
    from yoke_contracts.board.momentum_series import (
        _strategy_query,
        strategy_bytes_by_day,
    )

    project_ids = [1]
    net_change_sql, _ = _strategy_query(project_ids, 120, net_change=True)

    class _PayloadWithNetChange:
        def has_query(self, sql: str, params=None) -> bool:
            return True

        def query(self, sql: str, params=None):
            assert sql == net_change_sql
            return [("2026-07-05", 17)]

    assert strategy_bytes_by_day(
        _PayloadWithNetChange(), project_ids, days=120,
    ) == {"2026-07-05": 17}


def test_an_empty_day_stays_on_the_baseline_glyph() -> None:
    rendered = _build_sparkline([0, 5, 0, 9])
    assert rendered[0] == "▁"
    assert rendered[2] == "▁"
    assert rendered[1] != "▁"
