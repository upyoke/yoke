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


def test_an_empty_day_stays_on_the_baseline_glyph() -> None:
    rendered = _build_sparkline([0, 5, 0, 9])
    assert rendered[0] == "▁"
    assert rendered[2] == "▁"
    assert rendered[1] != "▁"
