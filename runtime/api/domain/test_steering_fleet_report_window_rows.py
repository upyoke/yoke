"""One report row per published plan-limit window, scoped and marked."""

from __future__ import annotations

from runtime.api.steering_fleet_test_helpers import PLAN_LIMIT_HOST, plan_limit_row
from yoke_core.domain.steering_fleet_plan_capacity import (
    ALL_MODELS_LABEL,
    MONTHLY_WINDOW,
    ROLLING_7D_WINDOW,
    TIGHTEST_NOTE,
    compute_plan_limit,
    plan_limit_lines,
    tightest_windows,
    window_label,
)
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit

_NOW = "2026-09-01T13:20:00Z"
_HOST = PLAN_LIMIT_HOST
_row = plan_limit_row


def _fleet_windows() -> tuple[MachinePlanLimit, ...]:
    """Every window three live vendors publish at once."""
    return (
        _row(
            surface="claude-cli",
            plan_tier="max",
            window_kind="rolling_5h",
            remaining_percent=79.0,
            resets_at="2026-09-01T22:50:00Z",
        ),
        _row(
            surface="claude-cli",
            plan_tier="max",
            window_kind="rolling_7d",
            remaining_percent=96.0,
            resets_at="2026-09-04T01:00:00Z",
        ),
        _row(
            surface="claude-cli",
            plan_tier="max",
            window_kind="rolling_7d",
            scope="Fable",
            remaining_percent=55.0,
            resets_at="2026-09-04T01:00:00Z",
        ),
        _row(
            surface="codex-cli",
            plan_tier="pro",
            window_kind="rolling_5h",
            scope="GPT-5.3-Codex-Spark",
            remaining_percent=100.0,
            resets_at="2026-09-02T00:30:00Z",
        ),
        _row(
            surface="codex-cli",
            plan_tier="pro",
            window_kind="rolling_7d",
            remaining_percent=81.0,
            resets_at="2026-09-07T13:06:00Z",
        ),
        _row(),
    )


def test_every_published_window_gets_its_own_row_naming_its_scope() -> None:
    lines = plan_limit_lines(_fleet_windows(), now=_NOW)
    windows = [
        line.split("|")[4].strip() for line in lines if line.startswith("| " + _HOST)
    ]
    assert windows == [
        "rolling 5h · all models",
        "weekly · Fable",
        "weekly · all models",
        "rolling 5h · GPT-5.3-Codex-Spark",
        "weekly · all models",
        "monthly · all models",
    ]


def test_the_binding_window_of_each_surface_is_the_one_marked_tightest() -> None:
    lines = plan_limit_lines(_fleet_windows(), now=_NOW)
    marked = {
        (line.split("|")[2].strip(), line.split("|")[4].strip())
        for line in lines
        if line.rstrip().endswith(f"{TIGHTEST_NOTE} |")
    }
    assert marked == {
        ("claude-cli", "weekly · Fable"),
        ("codex-cli", "weekly · all models"),
        ("cursor-cli", "monthly · all models"),
    }


def test_headroom_is_computed_from_each_window_own_length() -> None:
    scoped_weekly, monthly = (
        compute_plan_limit(
            _row(
                surface="claude-cli",
                window_kind="rolling_7d",
                scope="Fable",
                remaining_percent=50.0,
                resets_at="2026-09-02T13:20:00Z",
            ),
            now=_NOW,
        ),
        compute_plan_limit(
            _row(remaining_percent=50.0, resets_at="2026-09-02T13:20:00Z"),
            now=_NOW,
        ),
    )
    assert scoped_weekly.window == ROLLING_7D_WINDOW
    assert monthly.window == MONTHLY_WINDOW
    assert monthly.headroom_percent is not None
    assert scoped_weekly.headroom_percent is not None
    assert monthly.headroom_percent > scoped_weekly.headroom_percent


def test_an_unreadable_surface_is_never_the_tightest_row() -> None:
    binding = tightest_windows(
        (
            _row(
                surface="codex-cli",
                window_kind="unknown",
                remaining_percent=None,
                resets_at=None,
                status="unknown",
                reason="stale_credential",
            ),
        )
    )
    assert binding == frozenset()


def test_an_unreadable_window_names_no_scope_it_could_not_read() -> None:
    assert window_label("unknown", "all") == "unknown"
    assert window_label("monthly", "all") == f"monthly · {ALL_MODELS_LABEL}"
