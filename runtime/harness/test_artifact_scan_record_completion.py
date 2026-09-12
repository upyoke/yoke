"""A record wider than one read is finished, not abandoned mid-record.

The scan budget bounds how much one read starts. Stopping at it inside a
record would leave the resume offset in the middle of that record, and
the next read skips to the following newline — so everything the record
stated is lost, permanently, however small and however wanted. These
tests hold the three outcomes apart: the record is completed, completing
it does not turn the budget into a suggestion, and a record with no end
within the completion bound is abandoned once and said out loud.
"""

from __future__ import annotations

from pathlib import Path

from yoke_harness.artifact_scan import scan_rows

from runtime.harness.artifact_record_test_support import padded_row, write_rows


def test_a_record_wider_than_one_read_is_finished_rather_than_abandoned(
    tmp_path: Path,
) -> None:
    """Stopping at the bound would leave the offset inside the record."""
    seen: list[int] = []
    artifact = write_rows(
        tmp_path / "s.jsonl", [padded_row(1, 40_000), padded_row(2, 10)]
    )

    result = scan_rows(
        artifact,
        0,
        lambda row: seen.append(row["index"]),
        max_scan_bytes=5_000,
    )

    assert seen[0] == 1
    assert not result.oversized
    assert result.offset > 40_000


def test_finishing_one_record_does_not_turn_the_budget_into_a_suggestion(
    tmp_path: Path,
) -> None:
    """Past the budget, the record in flight ends the read, not the file."""
    artifact = write_rows(
        tmp_path / "s.jsonl", [padded_row(i, 40_000) for i in range(10)]
    )
    seen: list[int] = []

    result = scan_rows(
        artifact,
        0,
        lambda row: seen.append(row["index"]),
        max_scan_bytes=50_000,
    )

    assert seen == [0, 1]
    assert not result.caught_up
    assert result.bytes_read < artifact.stat().st_size


def test_a_record_wider_than_any_read_is_abandoned_once_and_said_out_loud(
    tmp_path: Path,
) -> None:
    """A record with no end in sight must not be read forever."""
    artifact = write_rows(tmp_path / "s.jsonl", [padded_row(1, 40_000), padded_row(2, 10)])
    gaps: list[int] = []
    seen: list[int] = []

    first = scan_rows(
        artifact,
        0,
        lambda row: seen.append(row["index"]),
        max_scan_bytes=5_000,
        max_record_completion_bytes=1_000,
        on_unrecoverable=lambda: gaps.append(1),
    )

    assert seen == []
    assert first.oversized
    assert gaps
    assert not first.caught_up
    offset = first.offset
    while not (
        result := scan_rows(
            artifact,
            offset,
            lambda row: seen.append(row["index"]),
            max_scan_bytes=5_000,
            max_record_completion_bytes=1_000,
        )
    ).caught_up:
        assert result.offset > offset
        offset = result.offset

    assert seen == [2]
