from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.timing_report import parse_timing_log, render_report


def test_render_report_marks_slowest(tmp_path: Path) -> None:
    log_file = tmp_path / "session.log"
    log_file.write_text(
        "\n".join(
            [
                "1700000000 2023-11-14T22:13:20Z sample/START",
                "1700000003 2023-11-14T22:13:23Z sample/READ elapsed=3s total=3s",
                "1700000013 2023-11-14T22:13:33Z sample/PROCESS elapsed=10s total=13s",
                "1700000016 2023-11-14T22:13:36Z sample/WRITE elapsed=3s total=16s",
                "1700000018 2023-11-14T22:13:38Z sample/END elapsed=2s total=18s [exit=0]",
            ]
        )
    )

    output = render_report(log_file)

    assert "Session: sample  Started: 2023-11-14T22:13:20Z" in output
    assert "PROCESS" in output
    assert "<- slowest" in output
    assert "Total: 18s" in output


def test_parse_timing_log_computes_total_from_end_epoch(tmp_path: Path) -> None:
    log_file = tmp_path / "session.log"
    log_file.write_text(
        "\n".join(
            [
                "1700000000 2023-11-14T22:13:20Z sample/START",
                "1700000003 2023-11-14T22:13:23Z sample/READ elapsed=3s total=3s",
                "1700000018 2023-11-14T22:13:38Z sample/END",
            ]
        )
    )

    _, _, total_time, rows = parse_timing_log(log_file)

    assert total_time == 18
    assert len(rows) == 1


def test_parse_timing_log_requires_start(tmp_path: Path) -> None:
    log_file = tmp_path / "session.log"
    log_file.write_text("1700000003 2023-11-14T22:13:23Z sample/READ elapsed=3s total=3s\n")

    with pytest.raises(ValueError, match="no START entry"):
        parse_timing_log(log_file)
