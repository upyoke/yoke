"""Composition decodes clocks only after their rows become relevant evidence."""

from runtime.api.domain.deployment_composition_clock_filters_test_support import (
    DRIVER_STAMP as DRIVER_STAMP,
    STAMP as STAMP,
    clocks as clocks,
    native_clock_columns,
)


from datetime import timedelta
from types import SimpleNamespace

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import deployment_run_carried_work_sources as sources
from yoke_core.domain.deployment_flow_succession import succession_chains


def _resolve(conn, times=None):
    times = {"a" * 40: STAMP} if times is None else times
    resolved, warnings = {}, []
    sources._resolve_item_metadata(
        conn,
        project_id=1,
        source=SimpleNamespace(
            commit_time=lambda commit: times[commit],
            resolve_commits=lambda refs: dict.fromkeys(refs, ""),
        ),
        base="b" * 40,
        head="a" * 40,
        commits=list(times),
        known_items={item_id: f"ITEM-{item_id}" for item_id in (1, 2, 3)},
        resolved=resolved,
        warnings=warnings,
    )
    assert warnings == []
    return resolved


@pytest.mark.parametrize("native", [False, True])
def test_composition_ignores_unrelated_historical_clocks(clocks, monkeypatch, native):
    if native:
        native_clock_columns(clocks)
    decoded = []

    def decode(value):
        decoded.append(value)
        return parse_instant(value)

    monkeypatch.setattr(sources, "parse_instant", decode)
    assert succession_chains(clocks, ["root", "unrelated"]) == {
        "root": ("root", "successor"),
        "unrelated": ("unrelated",),
    }
    assert _resolve(clocks) == {"a" * 40: {1}}
    assert decoded == [STAMP if native else format_instant(STAMP)]


@pytest.mark.parametrize("field", ["merged_at", "merge_queue_landed_at"])
def test_relevant_landing_clock_still_requires_strict_decoding(clocks, field):
    clocks.execute(
        f"UPDATE items SET {field}=%s WHERE id=1", ("2026-10-10 23:30:00.123456+00",)
    )
    with pytest.raises(InvalidInstant):
        _resolve(clocks)


def test_relevant_successor_clock_still_requires_strict_decoding(clocks):
    clocks.execute(
        "UPDATE deployment_flows SET created_at=%s WHERE id='successor'",
        ("2026-10-10 23:30:00.123456+00",),
    )
    with pytest.raises(InvalidInstant):
        succession_chains(clocks, ["root"])


@pytest.mark.parametrize("offset", [-600000001, -600000000, 600000000, 600000001])
def test_sql_window_preserves_inclusive_microsecond_cutoff(clocks, offset):
    clocks.execute(
        "UPDATE items SET merged_at=%s WHERE id=1",
        (format_instant(STAMP + timedelta(microseconds=offset)),),
    )
    expected = {"a" * 40: {1}} if abs(offset) <= 600000000 else {}
    assert _resolve(clocks) == expected


def test_unqualified_commit_clocks_do_not_decode_landing_candidates(clocks):
    assert _resolve(clocks, {"a" * 40: None}) == {}


@pytest.mark.parametrize("native", [False, True])
def test_empty_optional_landing_clocks_are_absent_in_sql_window(clocks, native):
    clocks.execute("UPDATE items SET merge_queue_landed_at='' WHERE id=1")
    clocks.execute("UPDATE items SET merged_at='',merge_queue_landed_at='' WHERE id=2")
    if native:
        native_clock_columns(clocks)
    assert _resolve(clocks) == {"a" * 40: {1}}


def test_recorded_commit_evidence_survives_outside_landing_window(clocks):
    clocks.execute("UPDATE items SET resolution_ref=%s WHERE id=2", ("a" * 40,))
    assert _resolve(clocks) == {"a" * 40: {1, 2}}
