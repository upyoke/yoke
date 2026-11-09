"""Permanent contracts for re-proving shipped migration invariants."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from yoke_core.domain.migration_fleet_applied_invariants import (
    RETIRED_STANDING_INVARIANTS,
    format_fleet_summary,
    skipped_standing_invariant_line,
    verify_applied_history_invariants,
)


def test_pending_entry_can_retire_an_applied_predecessor() -> None:
    def removed_surface(_conn: Any) -> None:
        raise AssertionError("retired surface is absent")

    modules = {
        "0001_presence": SimpleNamespace(invariants=removed_surface),
        "0002_removal": SimpleNamespace(RETIRES_INVARIANTS=("0001_presence",)),
    }

    report = verify_applied_history_invariants(
        object(),
        ("0001_presence",),
        history=tuple(modules),
        load_module=modules.__getitem__,
    )

    assert report.failure is None
    assert report.skipped == ()


def test_retired_standing_invariant_names_its_skip_and_reason(
    capsys: pytest.CaptureFixture[str],
    monkeypatch,
) -> None:
    name, reason = "8000_retired_check", "surface removed"
    monkeypatch.setitem(RETIRED_STANDING_INVARIANTS, name, reason)

    def wrong_standing_invariant(_conn: Any) -> None:
        raise AssertionError("this invariant must be skipped")

    report = verify_applied_history_invariants(
        object(),
        (name,),
        history=(name,),
        load_module=lambda _name: SimpleNamespace(invariants=wrong_standing_invariant),
    )

    assert report.failure is None
    assert report.skipped == ((name, reason),)
    assert capsys.readouterr().out == (
        f"converging {name}: standing invariant skipped -- {reason}\n"
    )


def test_fleet_summary_names_skipped_standing_invariants_beside_pass_fail(
    monkeypatch,
) -> None:
    name, reason = "8000_retired_check", "surface removed"
    monkeypatch.setitem(RETIRED_STANDING_INVARIANTS, name, reason)
    passed = SimpleNamespace(passed=True, skipped_invariants=((name, reason),))
    failed = SimpleNamespace(passed=False, skipped_invariants=())

    summary = format_fleet_summary((passed, passed, failed))

    assert summary.splitlines()[0] == "2 passed, 1 failed, 1 skipped"
    assert skipped_standing_invariant_line(name, reason) in summary.splitlines()
    assert (
        format_fleet_summary((SimpleNamespace(passed=True, skipped_invariants=()),))
        == "1 passed, 0 failed, 0 skipped"
    )
