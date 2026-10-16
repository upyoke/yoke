"""Board time windows use bounded database intervals."""

import re
from pathlib import Path
import pytest
from yoke_contracts.board.sql import days_ago_expr, days_ago_text_expr

_BOUNDED_OVERVIEW_WINDOWS = (30, 90, 120, 300, 365)
_DAYS_AGO_CALL = re.compile(r"days_ago_(?:text_)?expr\(([^)]+)\)")
_BOARD_ROOT = Path("packages/yoke-contracts/src/yoke_contracts/board")
_MOMENTUM_SIGNALS = Path(
    "packages/yoke-core/src/yoke_core/domain/board_momentum_signals.py"
)


@pytest.mark.parametrize("days", _BOUNDED_OVERVIEW_WINDOWS)
def test_bounded_windows_bake_a_stable_interval(days: int) -> None:
    sql = days_ago_text_expr(days)
    assert f"make_interval(days => {days})" in sql


def test_days_ago_refuses_a_non_positive_window() -> None:
    with pytest.raises(ValueError, match="positive"):
        days_ago_expr(0)
    with pytest.raises(ValueError, match="positive"):
        days_ago_text_expr(-1)


def test_days_ago_callers_do_not_pass_project_age() -> None:
    paths = list(_BOARD_ROOT.glob("*.py")) + [_MOMENTUM_SIGNALS]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for match in _DAYS_AGO_CALL.finditer(text):
            argument = match.group(1).lower()
            assert "project" not in argument, path
            assert "age" not in argument, path
