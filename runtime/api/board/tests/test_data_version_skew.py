"""Telling version skew apart from a genuine board record/replay parity bug.

A replay miss has two causes that look identical at the miss itself: the two
sides ran the same build and the query plan genuinely diverged, or they ran
different builds and the plan moved because the code did. Calling the second
a parity bug sends the reader to debug code that is fine, which is what it
did before this split existed.
"""

from __future__ import annotations

import pytest

from yoke_contracts.board.data import (
    BOARD_DATA_VERSION,
    BoardDataMissError,
    ReplayBoardDB,
)

_SQL = "SELECT id FROM items WHERE project_id = %s"


def _payload(engine_version: str | None) -> dict:
    payload: dict = {
        "version": BOARD_DATA_VERSION,
        "scope": "all",
        "entries": [
            {"kind": "query", "sql": _SQL, "params": [1], "rows": [[7]]},
        ],
    }
    if engine_version is not None:
        payload["engine_version"] = engine_version
    return payload


def _miss(payload: dict, monkeypatch, local_version: str) -> str:
    monkeypatch.setattr(
        "yoke_contracts.engine_version.installed_engine_version",
        lambda: local_version,
    )
    replay = ReplayBoardDB.from_payload(payload)
    with pytest.raises(BoardDataMissError) as excinfo:
        # Same SQL, different params — a plan the payload does not carry.
        replay.query(_SQL, (2,))
    return str(excinfo.value)


def test_differing_builds_report_skew_and_name_both(monkeypatch):
    """The observed case: a source checkout ahead of a deployed server."""
    message = _miss(_payload("0.1.1+launch.183"), monkeypatch, "0.1.1+launch.185")
    assert "0.1.1+launch.183" in message
    assert "0.1.1+launch.185" in message
    assert "version skew" in message
    # It may mention a parity bug, but only to rule it out.
    assert "rather than a parity bug" in message


def test_differing_builds_name_the_remedy(monkeypatch):
    """Naming the cause without the fix leaves the reader where they were."""
    message = _miss(_payload("0.1.1+launch.183"), monkeypatch, "0.1.1+launch.185")
    assert "deploy" in message
    assert "pin" in message


def test_matching_builds_still_report_a_parity_bug(monkeypatch):
    """The split must not swallow the real defect it used to always claim."""
    message = _miss(_payload("0.1.1+launch.185"), monkeypatch, "0.1.1+launch.185")
    assert "parity bug" in message
    assert "skew" not in message


def test_a_payload_with_no_recorded_version_reports_unknown(monkeypatch):
    """Older payloads predate the recorded version and must not be guessed at."""
    message = _miss(_payload(None), monkeypatch, "0.1.1+launch.185")
    assert "cannot be told apart" in message
    assert "parity bug" in message  # named as the thing that CANNOT be concluded
    assert "0.1.1+launch.185" in message


def test_an_unresolvable_local_version_names_version_skew(monkeypatch):
    """A source checkout resolves no version — the likeliest skew case.

    Reporting that as agreement, or as an unexplained mismatch, would
    send the reader to debug code that is fine.
    """
    message = _miss(_payload("0.1.1+launch.183"), monkeypatch, "")
    assert "version skew" in message
    assert "0.1.1+launch.183" in message
    assert "parity bug" in message  # named as the thing this is not


def test_neither_side_known_says_so_plainly(monkeypatch):
    message = _miss(_payload(None), monkeypatch, "")
    assert "neither side reports an engine version" in message


def test_the_miss_still_names_the_query_it_could_not_serve(monkeypatch):
    """The diagnosis is added to the existing detail, not swapped for it."""
    message = _miss(_payload("0.1.1+launch.185"), monkeypatch, "0.1.1+launch.185")
    assert "no recorded query result" in message
    assert "SELECT id FROM items" in message
