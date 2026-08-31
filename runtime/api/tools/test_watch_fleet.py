"""The ``yoke watch fleet`` wrapper: registration, classes, and captures."""

from __future__ import annotations

import io
from pathlib import Path

from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS, cli_form
from yoke_core.domain.steering_fleet_report_render import REPORT_BEGIN, REPORT_END
from yoke_core.tools import watch_fleet
from yoke_core.tools._watch_throttle import LineClass
from yoke_core.tools.watch_entrypoints import WRAPPER_MAINS
from yoke_core.tools.watch_inventory import EXCLUDE_PATHS, FALLBACK_TOKENS


def test_the_wrapper_is_registered_on_every_roster() -> None:
    """A wrapper missing from one roster is a wrapper agents cannot reach."""
    assert WATCH_CLI_TOKENS[watch_fleet.WRAPPER_MODULE] == ("watch", "fleet")
    assert cli_form(watch_fleet.WRAPPER_MODULE) == "yoke watch fleet"
    assert WRAPPER_MAINS[watch_fleet.WRAPPER_MODULE] is watch_fleet.main
    assert watch_fleet.WRAPPER_MODULE.replace("yoke_core.tools.", "") in FALLBACK_TOKENS
    assert "packages/yoke-core/src/yoke_core/tools/watch_fleet.py" in EXCLUDE_PATHS


def test_the_cli_usage_table_carries_the_command() -> None:
    from yoke_cli.commands.watchers import (
        TOOL_SHAPED_SUBCOMMANDS,
        TOOL_SHAPED_USAGE,
    )

    assert ("watch", "fleet") in TOOL_SHAPED_SUBCOMMANDS
    assert "yoke watch fleet" in TOOL_SHAPED_USAGE


def test_actionable_delta_kinds_are_immediate() -> None:
    for line in (
        "fleet ALARM idle-holder session=a items=YOK-1 idle=41m surface=x",
        "fleet ALARM unowned-item YOK-1 status=implementing unowned=15m",
        "fleet ALARM starved-envelope message=m recipient=a pending=10m",
        "fleet inbox msg-1 state=pending from=w",
        "fleet session abc terminated surface=codex-cli",
        "fleet item YOK-1 status implementing -> blocked",
        "fleet ERROR read failed sessions.list: unreachable (attempt 1/3)",
        "fleet FATAL read failed sessions.list: unreachable",
        "Traceback (most recent call last):",
        "RuntimeError: boom",
    ):
        assert watch_fleet.classify_fleet_line(line).cls is LineClass.URGENT


def test_routine_deltas_are_silent_until_a_report_wake() -> None:
    for line in (
        "fleet item YOK-1 status idea -> implementing",
        "fleet item YOK-1 claim unclaimed -> claimed_by_other_live",
        "fleet session abc registered surface=codex-cli mode=dash",
        "fleet session abc ended surface=codex-cli",
        "fleet CLEAR idle-holder session=a",
    ):
        assert watch_fleet.classify_fleet_line(line).cls is LineClass.NOISE

    assert watch_fleet.classify_fleet_line(REPORT_BEGIN).cls is LineClass.URGENT
    assert watch_fleet.classify_fleet_line(REPORT_END).cls is LineClass.NOISE


def test_unrecognized_output_is_noise() -> None:
    classified = watch_fleet.classify_fleet_line("some incidental chatter\n")
    assert classified.cls is LineClass.NOISE


def test_the_probe_argv_targets_the_fleet_delta_probe() -> None:
    argv = watch_fleet._probe_argv(["--project", "yoke"])
    assert argv[1:] == [
        "-m",
        "yoke_core.domain.fleet_delta_probe",
        "--project",
        "yoke",
    ]


def test_print_streaming_pair_emits_the_background_monitor_inspect_triple(
    monkeypatch, tmp_path: Path
) -> None:
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    monkeypatch.setattr(
        watch_fleet._watch_runner,
        "mint_capture_paths",
        lambda kind: (raw, progress),
    )
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)

    assert watch_fleet.main(["--print-streaming-pair", "--", "--project", "yoke"]) == 0
    output = captured.getvalue()
    assert "yoke watch fleet" in output
    assert f"--raw-capture {raw}" in output
    assert "yoke watch tail" in output
    assert str(progress) in output
    assert f"tail -80 {raw}" in output


def test_the_wrapper_writes_the_exit_sentinel_a_follower_can_exit_on(
    tmp_path: Path,
) -> None:
    """`watch_tail` exits only on this footer; a missing one hangs a Monitor."""
    from yoke_core.tools.watch_tail import EXIT_SENTINEL

    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    code = watch_fleet.main(
        [
            "--raw-capture",
            str(raw),
            "--progress-capture",
            str(progress),
            "--",
            "--interval",
            "0",
        ]
    )
    assert code == 2
    sentinel_lines = [
        line for line in progress.read_text().splitlines() if EXIT_SENTINEL.match(line)
    ]
    assert sentinel_lines == ["# watch_fleet exit=2 raw=" + str(raw)]
