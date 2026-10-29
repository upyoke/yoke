"""The fleet watcher's wake stream carries only rows that changed.

Every pass re-listed every row, and the ages in them ("for 1h32m",
"quiet 42m", "pending=10m") made each one look new, so steering piped
the stream through grep and an awk dedupe to read it. A row now reaches
the wake stream when it is new or changed apart from its elapsed-time
fields; the raw capture still holds every report whole.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.steering_fleet_report_render import REPORT_BEGIN, REPORT_END
from yoke_core.tools import watch_fleet
from yoke_core.tools._fleet_report_changes import changed_lines, row_identity

from runtime.api.tools.watch_fleet_test_harness import (
    RecordingStream,
    run_probe_script,
)

RUN_ROW = "  ! run-20261016-011 executing · stage item-qa for {age} · 3 of 20 outstanding, 1 red"
RED_ROW = "      red: run-wide #47771 fail"
HOLDER_ROW = "  YOK-4174  session ccd06717  mode dash  quiet {age}"


def _report(*rows: str, composed: str = "2026-10-16T19:00:00Z") -> list[str]:
    return [
        REPORT_BEGIN,
        f"composed {composed} · 1 held scopes · hook digest",
        "deployment runs:",
        *rows,
        "",
        REPORT_END,
    ]


def _feed(classify: watch_fleet.FleetLineClassifier, lines: list[str]) -> str | None:
    for line in lines:
        classify(line)
    return classify.flush_held()


def test_ages_and_instants_do_not_make_a_row_new() -> None:
    assert row_identity(RUN_ROW.format(age="1h32m")) == row_identity(
        RUN_ROW.format(age="1h34m")
    )
    assert row_identity("fleet ALARM starved-envelope pending=10m") == row_identity(
        "fleet ALARM starved-envelope pending=12m"
    )
    assert row_identity("composed 2026-10-16T19:00:00Z") == row_identity(
        "composed 2026-10-16T19:02:07.5Z"
    )
    assert row_identity(RED_ROW) != row_identity(RED_ROW.replace("47771", "47772"))


def test_an_unchanged_report_after_the_first_wakes_nobody() -> None:
    classify = watch_fleet.make_fleet_classifier()
    first = _feed(classify, _report(RUN_ROW.format(age="1h32m"), RED_ROW))
    assert first is not None and "item-qa for 1h32m" in first

    again = _feed(
        classify,
        _report(RUN_ROW.format(age="1h34m"), RED_ROW, composed="2026-10-16T19:02:00Z"),
    )

    assert again is None


def test_a_changed_row_arrives_with_the_lines_it_sits_under() -> None:
    classify = watch_fleet.make_fleet_classifier()
    _feed(classify, _report(RUN_ROW.format(age="1h32m"), RED_ROW))

    changed = _feed(
        classify,
        _report(
            RUN_ROW.format(age="1h34m"),
            RED_ROW.replace("47771", "47772"),
            HOLDER_ROW.format(age="42m"),
        ),
    )

    assert changed is not None
    lines = changed.splitlines()
    assert lines[0] == REPORT_BEGIN and lines[-1] == REPORT_END
    assert lines[1].startswith("composed ")
    assert "deployment runs:" in lines
    assert RUN_ROW.format(age="1h34m") in lines
    assert RED_ROW.replace("47771", "47772") in lines
    assert HOLDER_ROW.format(age="42m") in lines
    assert RED_ROW not in lines


def test_an_unchanged_parent_stays_out_without_a_changed_child() -> None:
    body = ["deployment runs:", "  run a", "    detail a", "  run b", "    detail b"]
    seen = {row_identity(line) for line in body}
    later = [*body[:4], "    detail b changed"]

    assert changed_lines(later, seen) == [
        "deployment runs (changes only):",
        "  run b",
        "    detail b changed",
    ]


def test_the_raw_capture_keeps_every_report_whole(tmp_path: Path) -> None:
    stdout = RecordingStream()
    reports = [
        _report(RUN_ROW.format(age="1h32m"), RED_ROW),
        _report(RUN_ROW.format(age="1h34m"), RED_ROW),
    ]
    printed = "\n".join(line for report in reports for line in report)
    code = run_probe_script(tmp_path, f"print({printed!r})\n", stdout)

    assert code == 0
    raw = (tmp_path / "raw.log").read_text(encoding="utf-8")
    assert "item-qa for 1h32m" in raw and "item-qa for 1h34m" in raw
    progress = (tmp_path / "progress.log").read_text(encoding="utf-8")
    assert progress.count(REPORT_BEGIN) == 1
    assert "item-qa for 1h34m" not in progress


def test_partial_available_heading_and_unsuffixed_seen_rows() -> None:
    heading = "available — runnable and unclaimed"
    first = [heading, "  item one", "  item two"]
    seen = {row_identity(line) for line in first}
    later = [heading, "  item one changed", "  item two"]
    assert changed_lines(later, seen) == [
        "available (changes only) — runnable and unclaimed", "  item one changed"
    ]
    assert heading in seen
    assert not any("changes only" in line for line in seen)
    classify = watch_fleet.make_fleet_classifier()
    _feed(classify, _report(*first))
    assert "changes only" in _feed(classify, _report(*later))
    assert _feed(classify, _report(*later)) is None


def test_whole_new_section_keeps_its_heading() -> None:
    body = ["available:", "  item one", "  item two"]
    assert changed_lines(body, set()) == body


def test_partial_run_headings_use_the_same_suffix_rules() -> None:
    body = ["runs:", "  run one", "    old detail", "    new detail"]
    seen = {row_identity(line) for line in body[:-1]}
    assert changed_lines(body, seen) == [
        "runs (changes only):", "  run one (changes only)", "    new detail"
    ]
