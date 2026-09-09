"""Reading a growing transcript costs its bounds, not its size.

Every fixture here is a small artifact whose shape is the one that hurt in
production: a record far larger than a turn, an artifact that gained more
than one read folds, and mostly-ASCII text carrying the one non-ASCII
character that widens Python's whole string.
"""

from __future__ import annotations

import json
import tracemalloc
from pathlib import Path

import pytest

from yoke_harness import artifact_scan
from yoke_harness.artifact_scan import (
    MAX_TAIL_BYTES,
    iter_rows,
    scan_rows,
    tail_rows_newest_first,
)


def _write(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return path


def _padded(index: int, size: int, filler: str = "a") -> dict:
    return {"index": index, "filler": filler * size}


def test_a_fold_holds_accumulators_rather_than_the_bytes_it_read(
    tmp_path: Path,
) -> None:
    """Peak allocation tracks one record, not the artifact."""
    artifact = _write(tmp_path / "big.jsonl", [_padded(i, 200_000) for i in range(8)])
    counted = 0

    def fold(row: dict) -> None:
        nonlocal counted
        counted += 1

    tracemalloc.start()
    try:
        result = scan_rows(artifact, 0, fold)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert counted == 8
    assert result.caught_up
    assert result.offset == artifact.stat().st_size
    assert peak < artifact.stat().st_size


def test_one_wide_character_does_not_multiply_the_whole_artifact(
    tmp_path: Path,
) -> None:
    """Python stores a string containing one emoji four bytes per character."""
    artifact = _write(
        tmp_path / "wide.jsonl", [_padded(i, 200_000, "a") for i in range(4)]
    )
    with artifact.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_padded(9, 200_000, "a") | {"emoji": "🙂"}) + "\n")

    tracemalloc.start()
    try:
        scan_rows(artifact, 0, lambda row: None)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < artifact.stat().st_size


def test_an_oversized_record_is_skipped_and_said_out_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(artifact_scan, "MAX_RECORD_BYTES", 1_000)
    artifact = _write(
        tmp_path / "s.jsonl", [_padded(1, 10), _padded(2, 5_000), _padded(3, 10)]
    )
    seen: list[int] = []

    result = scan_rows(artifact, 0, lambda row: seen.append(row["index"]))

    assert seen == [1, 3]
    assert result.oversized
    assert result.offset == artifact.stat().st_size


def test_an_oversized_record_without_its_newline_yet_is_not_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bytes are dropped as they arrive, not buffered awaiting an end."""
    monkeypatch.setattr(artifact_scan, "MAX_RECORD_BYTES", 1_000)
    artifact = tmp_path / "s.jsonl"
    artifact.write_text(json.dumps(_padded(1, 10)) + "\n" + "x" * 40_000)

    result = scan_rows(artifact, 0, lambda row: None)

    assert result.oversized


def test_a_read_that_stops_short_says_so_and_the_next_one_resumes(
    tmp_path: Path,
) -> None:
    artifact = _write(tmp_path / "s.jsonl", [_padded(i, 20_000) for i in range(10)])
    first: list[int] = []

    early = scan_rows(
        artifact, 0, lambda row: first.append(row["index"]), max_scan_bytes=50_000
    )

    assert not early.caught_up
    assert 0 < early.offset < artifact.stat().st_size
    second: list[int] = []

    later = scan_rows(artifact, early.offset, lambda row: second.append(row["index"]))

    assert later.caught_up
    assert first + second == list(range(10))


def test_a_record_wider_than_one_read_does_not_stall_the_fold(
    tmp_path: Path,
) -> None:
    """Folding nothing at the bound would repeat forever at one offset."""
    artifact = _write(tmp_path / "s.jsonl", [_padded(1, 40_000), _padded(2, 10)])

    first = scan_rows(artifact, 0, lambda row: None, max_scan_bytes=5_000)

    assert first.offset > 0
    assert first.oversized
    assert not first.caught_up
    seen: list[int] = []
    offset = first.offset
    while not (
        result := scan_rows(
            artifact,
            offset,
            lambda row: seen.append(row["index"]),
            max_scan_bytes=5_000,
        )
    ).caught_up:
        assert result.offset > offset
        offset = result.offset

    assert seen == [2]


def test_a_read_that_reaches_the_end_exactly_at_its_bound_is_caught_up(
    tmp_path: Path,
) -> None:
    artifact = _write(tmp_path / "s.jsonl", [_padded(0, 10)])

    result = scan_rows(
        artifact, 0, lambda row: None, max_scan_bytes=artifact.stat().st_size
    )

    assert result.caught_up


def test_a_trailing_partial_record_waits_for_its_newline(tmp_path: Path) -> None:
    artifact = _write(tmp_path / "s.jsonl", [_padded(1, 10)])
    complete = artifact.stat().st_size
    with artifact.open("a") as handle:
        handle.write(json.dumps(_padded(2, 10))[:20])
    seen: list[int] = []

    result = scan_rows(artifact, 0, lambda row: seen.append(row["index"]))

    assert seen == [1]
    assert result.offset == complete


def test_unparsable_and_non_object_records_are_dropped_not_fatal(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "s.jsonl"
    artifact.write_text('{"index": 1}\nnot json\n[1, 2]\n\n{"index": 2}\n')
    seen: list[int] = []

    scan_rows(artifact, 0, lambda row: seen.append(row["index"]))

    assert seen == [1, 2]


def test_a_missing_artifact_folds_nothing_and_keeps_its_offset(
    tmp_path: Path,
) -> None:
    result = scan_rows(tmp_path / "absent.jsonl", 17, lambda row: None)

    assert result.offset == 17
    assert result.caught_up


def test_iteration_stops_where_its_reader_stops(tmp_path: Path) -> None:
    """A reader that has what it came for never reads the rest."""
    artifact = _write(tmp_path / "s.jsonl", [_padded(i, 100_000) for i in range(10)])

    tracemalloc.start()
    try:
        for row in iter_rows(artifact):
            if row["index"] == 0:
                break
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < artifact.stat().st_size


def test_a_final_record_without_its_newline_is_still_iterated(
    tmp_path: Path,
) -> None:
    """An identity scan advances no offset, so it reads the last record."""
    artifact = tmp_path / "s.jsonl"
    artifact.write_text(json.dumps(_padded(1, 10)))

    assert [row["index"] for row in iter_rows(artifact)] == [1]


def test_a_final_oversized_record_without_its_newline_is_not_iterated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(artifact_scan, "MAX_RECORD_BYTES", 1_000)
    artifact = tmp_path / "s.jsonl"
    artifact.write_text(json.dumps(_padded(1, 10)) + "\n" + "x" * 40_000)

    assert [row["index"] for row in iter_rows(artifact)] == [1]


def test_a_fold_leaves_a_final_record_without_its_newline_for_next_time(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "s.jsonl"
    artifact.write_text(json.dumps(_padded(1, 10)))
    seen: list[int] = []

    result = scan_rows(artifact, 0, lambda row: seen.append(row["index"]))

    assert seen == []
    assert result.offset == 0


def test_the_newest_records_are_read_from_the_end(tmp_path: Path) -> None:
    artifact = _write(tmp_path / "s.jsonl", [_padded(i, 50_000) for i in range(20)])

    rows = list(tail_rows_newest_first(artifact, max_rows=2, max_bytes=200_000))

    assert [row["index"] for row in rows] == [19, 18]


def test_the_record_the_tail_window_cut_in_half_is_dropped(tmp_path: Path) -> None:
    artifact = _write(tmp_path / "s.jsonl", [_padded(i, 10_000) for i in range(5)])

    rows = list(tail_rows_newest_first(artifact, max_bytes=15_000))

    assert [row["index"] for row in rows] == [4]


def test_a_tail_read_costs_its_window_rather_than_the_artifact(
    tmp_path: Path,
) -> None:
    """A reader taking the newest match never parses the window's rest."""
    artifact = _write(tmp_path / "s.jsonl", [_padded(i, 200_000) for i in range(30)])

    tracemalloc.start()
    try:
        newest = next(iter(tail_rows_newest_first(artifact)))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert newest["index"] == 29
    assert peak < 2 * MAX_TAIL_BYTES


def test_a_half_written_final_record_is_dropped_by_the_tail_read(
    tmp_path: Path,
) -> None:
    """It is not valid JSON, so the newest complete record still wins."""
    artifact = _write(tmp_path / "s.jsonl", [_padded(1, 10)])
    with artifact.open("a") as handle:
        handle.write(json.dumps(_padded(2, 10))[:20])

    rows = list(tail_rows_newest_first(artifact))

    assert [row["index"] for row in rows] == [1]


def test_a_complete_final_record_without_its_newline_is_read(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "s.jsonl"
    artifact.write_text(json.dumps(_padded(1, 10)))

    rows = list(tail_rows_newest_first(artifact))

    assert [row["index"] for row in rows] == [1]


def test_a_tail_smaller_than_its_window_reads_every_record(tmp_path: Path) -> None:
    artifact = _write(tmp_path / "s.jsonl", [_padded(i, 10) for i in range(3)])

    rows = list(tail_rows_newest_first(artifact))

    assert [row["index"] for row in rows] == [2, 1, 0]
