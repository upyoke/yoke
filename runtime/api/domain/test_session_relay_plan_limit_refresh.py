"""Plan-limit refreshes leave enough time before displayed readings expire."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.organization_contract.fleet_keys import FLEET_KEY_SPECS
from yoke_contracts.session_control.plan_limits import (
    PLAN_LIMIT_FRESH_SECONDS,
    PLAN_LIMIT_REFRESH_SECONDS,
    plan_limit_window,
    surface_reading,
    unknown_reading,
)
from yoke_harness import session_relay_plan_limits
from yoke_harness.session_relay_plan_limit_http import (
    PLAN_LIMIT_PROBE_TIMEOUT_SECONDS,
)
from yoke_harness.session_relay_report_delivery import (
    RELAY_REPORT_TIMEOUT_SECONDS,
)


SURFACE = "codex-cli"
FIRST_OBSERVED_AT = "2026-09-04T12:00:00Z"
REFRESHED_AT = "2026-09-04T12:04:00Z"


def _reading(observed_at: str) -> dict[str, object]:
    return surface_reading(
        SURFACE,
        observed_at=observed_at,
        plan_tier="pro",
        windows=(
            plan_limit_window(
                window_kind="rolling_5h",
                scope="all",
                meter="primary",
                remaining_percent=72,
                resets_at="2026-09-04T14:00:00Z",
            ),
        ),
    )


def test_refresh_policy_covers_the_bounded_probe_and_delivery_path() -> None:
    relay_poll_seconds = int(FLEET_KEY_SPECS["fleet.relay_poll_seconds"].default)
    refresh_reserve = PLAN_LIMIT_FRESH_SECONDS - PLAN_LIMIT_REFRESH_SECONDS
    # Cursor has the longest existing path: two HTTP reads and, when its plan
    # read fails, one bounded CLI fallback before the bounded relay report.
    longest_normal_path = (
        3 * PLAN_LIMIT_PROBE_TIMEOUT_SECONDS + RELAY_REPORT_TIMEOUT_SECONDS
    )

    assert PLAN_LIMIT_REFRESH_SECONDS == 4 * 60
    assert PLAN_LIMIT_FRESH_SECONDS == 5 * 60
    assert PLAN_LIMIT_REFRESH_SECONDS % relay_poll_seconds == 0
    assert longest_normal_path < refresh_reserve


def test_cached_reading_refreshes_before_the_display_deadline(
    monkeypatch,
    tmp_path: Path,
) -> None:
    observed: list[str] = []

    def probe(*, observed_at: str) -> dict[str, object]:
        observed.append(observed_at)
        return _reading(observed_at)

    monkeypatch.setitem(session_relay_plan_limits._PROBES, SURFACE, probe)

    first = session_relay_plan_limits.observe_plan_limits(
        (SURFACE,), state_dir=tmp_path, now=0, clock=lambda: FIRST_OBSERVED_AT
    )
    cached = session_relay_plan_limits.observe_plan_limits(
        (SURFACE,),
        state_dir=tmp_path,
        now=PLAN_LIMIT_REFRESH_SECONDS - 1,
        clock=lambda: "unexpected-refresh",
    )
    refreshed = session_relay_plan_limits.observe_plan_limits(
        (SURFACE,),
        state_dir=tmp_path,
        now=PLAN_LIMIT_REFRESH_SECONDS,
        clock=lambda: REFRESHED_AT,
    )

    assert first[SURFACE]["observed_at"] == FIRST_OBSERVED_AT
    assert cached[SURFACE]["observed_at"] == FIRST_OBSERVED_AT
    assert refreshed[SURFACE]["observed_at"] == REFRESHED_AT
    assert observed == [FIRST_OBSERVED_AT, REFRESHED_AT]


def test_failed_refresh_replaces_old_quota_with_a_named_unknown(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setitem(
        session_relay_plan_limits._PROBES,
        SURFACE,
        lambda *, observed_at: _reading(observed_at),
    )
    session_relay_plan_limits.observe_plan_limits(
        (SURFACE,), state_dir=tmp_path, now=0, clock=lambda: FIRST_OBSERVED_AT
    )
    monkeypatch.setitem(
        session_relay_plan_limits._PROBES,
        SURFACE,
        lambda *, observed_at: unknown_reading(
            SURFACE, "http_503", observed_at=observed_at
        ),
    )

    failed = session_relay_plan_limits.observe_plan_limits(
        (SURFACE,),
        state_dir=tmp_path,
        now=PLAN_LIMIT_REFRESH_SECONDS,
        clock=lambda: REFRESHED_AT,
    )[SURFACE]

    assert failed["observed_at"] == REFRESHED_AT
    assert failed["plan_tier"] is None
    assert failed["windows"] == [
        {
            "window_kind": "unknown",
            "scope": "all",
            "meter": "unknown",
            "remaining_percent": None,
            "resets_at": None,
            "status": "unknown",
            "reason": "http_503",
        }
    ]
