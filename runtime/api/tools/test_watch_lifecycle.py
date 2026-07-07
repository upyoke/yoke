"""Tests for ``yoke_core.tools.watch_lifecycle``.

Covers the line classifier against representative lifecycle-writer
output fixtures, sub-command dispatch (``items-update-status`` and
``repair-status``), position-tolerant ``--`` separator parsing,
``--print-streaming-pair`` shape, exit-code passthrough, and the
sentinel-driven auto-exit.
"""

from __future__ import annotations

import io
import sys

import pytest

from yoke_core.tools import _watch_runner, watch_lifecycle
from yoke_core.tools._watch_runner import filter_match
from yoke_core.tools._watch_throttle import LineClass


class TestLifecycleClassifier:
    @pytest.mark.parametrize(
        "line",
        [
            "--- Populating merged_at (pre-flight) ---",
            "  merged_at already set: 2026-05-19T10:00:00Z",
            "  merged_at set to 2026-05-19T10:00:00Z",
            "  Promoted: task 5 (reviewed-implementation -> done)",
            "  Cascaded: task 3 (reviewed-implementation -> done)",
            "  GitHub: #123 labeled+commented+closed",
            "Status is still 'reviewed-implementation' — retrying in 2 seconds...",
            "Installing project dependencies",
            "Rebuilding board (50/300 items)",
            "Syncing GitHub for YOK-1755",
        ],
    )
    def test_progress_lines_classify(self, line: str) -> None:
        cls = watch_lifecycle.classify_lifecycle_line(line)
        assert cls.cls is LineClass.PROGRESS

    @pytest.mark.parametrize(
        "line",
        [
            "Error: Item YOK-9999 not found.",
            "ERROR: invalid status: 'frob'",
            "Warning: validation surface degraded",
            "BLOCKED: YOK-1 has no acceptance criteria.",
            "Status update failed after 3 attempts.",
            "Usage: repair-status <item>",
            "HARD STOP: User-authored files at risk.",
            "GATE_HARD_BLOCK: dep not in terminal status",
        ],
    )
    def test_urgent_lines_classify(self, line: str) -> None:
        cls = watch_lifecycle.classify_lifecycle_line(line)
        assert cls.cls is LineClass.URGENT

    @pytest.mark.parametrize(
        "line",
        [
            "=== Done transition: YOK-1755 ===",
            "=== Step 6: Update status to done ===",
            "=== Step 6b: Epic sub-task cascade ===",
            "Status verified: done (exit code was from a different gate)",
            "Sub-task cascade complete: 3 cascaded, 0 promoted",
            "Batch GitHub sync complete.",
            "RESULT_FILE=/tmp/result.json",
            "YOKE_REPO_ROOT=/Users/foo/yoke",
            '{"success": true, "item_id": 1755}',
            '{"item_id": 1755, "status": "implementing"}',
            '{"outcome": "completed"}',
        ],
    )
    def test_summary_lines_classify(self, line: str) -> None:
        cls = watch_lifecycle.classify_lifecycle_line(line)
        assert cls.cls is LineClass.SUMMARY

    @pytest.mark.parametrize(
        "line",
        [
            "  resolving DB path...",
            "irrelevant noise",
            "some untagged debug output",
            "",
        ],
    )
    def test_noise_lines_classify(self, line: str) -> None:
        cls = watch_lifecycle.classify_lifecycle_line(line)
        assert cls.cls is LineClass.NOISE


class TestUnionPattern:
    def test_progress_lines_match_union(self) -> None:
        for line in (
            "--- Step ---",
            "  Promoted: task 1",
            "Status is still 'foo'",
        ):
            assert filter_match(watch_lifecycle.LIFECYCLE_PROGRESS_PATTERN, line)

    def test_urgent_lines_match_union(self) -> None:
        for line in (
            "Error: bad",
            "BLOCKED: missing AC",
            "GATE_REVIEW_FAILED: ...",
        ):
            assert filter_match(watch_lifecycle.LIFECYCLE_PROGRESS_PATTERN, line)

    def test_summary_lines_match_union(self) -> None:
        for line in (
            "=== Done transition: YOK-1 ===",
            "Status verified: done",
            '{"success": true}',
            "RESULT_FILE=/tmp/x.json",
        ):
            assert filter_match(watch_lifecycle.LIFECYCLE_PROGRESS_PATTERN, line)


class TestSubcommandResolution:
    def test_items_update_status_maps_to_db_router(self) -> None:
        module, prefix, passthrough = watch_lifecycle._resolve_subcommand(
            ["items-update-status", "YOK-1755", "status", "implementing"]
        )
        assert module == "yoke_core.cli.db_router"
        assert prefix == ("items", "update")
        assert passthrough == ["YOK-1755", "status", "implementing"]

    def test_repair_status_maps_to_engine(self) -> None:
        module, prefix, passthrough = watch_lifecycle._resolve_subcommand(
            ["repair-status", "YOK-1755"]
        )
        assert module == "yoke_core.engines.repair_status"
        assert prefix == ()
        assert passthrough == ["YOK-1755"]

    def test_unknown_subcommand_exits_with_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            watch_lifecycle._resolve_subcommand(["unknown-thing"])
        assert excinfo.value.code == 2
        err = capsys.readouterr().err
        assert "unknown sub-command" in err
        assert "items-update-status" in err
        assert "repair-status" in err

    def test_missing_subcommand_exits_with_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            watch_lifecycle._resolve_subcommand([])
        assert excinfo.value.code == 2
        err = capsys.readouterr().err
        assert "missing sub-command" in err


class TestEngineArgv:
    def test_db_router_argv_includes_prefix(self) -> None:
        argv = watch_lifecycle._engine_argv(
            "yoke_core.cli.db_router", ("items", "update"),
            ["YOK-1", "status", "implementing"],
        )
        assert argv[0] == sys.executable
        assert argv[1:] == [
            "-m", "yoke_core.cli.db_router",
            "items", "update", "YOK-1", "status", "implementing",
        ]

    def test_repair_status_argv_omits_prefix(self) -> None:
        argv = watch_lifecycle._engine_argv(
            "yoke_core.engines.repair_status", (), ["YOK-1"],
        )
        assert argv == [
            sys.executable, "-m", "yoke_core.engines.repair_status", "YOK-1",
        ]


class TestPrintStreamingPair:
    def test_print_streaming_pair_emits_three_line_block(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = watch_lifecycle.main(
            ["--print-streaming-pair", "items-update-status",
             "--", "YOK-1", "status", "implementing"]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "yoke_core.tools.watch_lifecycle" in out
        assert "--raw-capture" in out
        assert "--progress-capture" in out
        assert "items-update-status" in out
        assert "YOK-1" in out
        assert "yoke_core.tools.watch_tail" in out
        assert "tail -80" in out

    def test_print_streaming_pair_flag_position_tolerant(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Flag placed AFTER the subcommand still pre-extracted.
        rc = watch_lifecycle.main(
            ["repair-status", "--print-streaming-pair", "--", "YOK-1"]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "repair-status" in out
        assert "YOK-1" in out

    def test_print_streaming_pair_rejects_unknown_subcommand(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = watch_lifecycle.main(
            ["--print-streaming-pair", "frobnicate", "--", "YOK-1"]
        )
        assert rc == 2
        err = capsys.readouterr().err
        assert "unknown sub-command" in err


class TestPassthroughSeparator:
    def test_leading_separator_is_stripped(self) -> None:
        ns = watch_lifecycle._parse_args(
            ["--", "items-update-status", "YOK-1"]
        )
        stripped = watch_lifecycle._strip_separator(list(ns.passthrough))
        assert stripped == ["items-update-status", "YOK-1"]

    def test_separator_after_subcommand_is_stripped(self) -> None:
        ns = watch_lifecycle._parse_args(
            ["items-update-status", "--", "YOK-1", "status", "implementing"]
        )
        stripped = watch_lifecycle._strip_separator(list(ns.passthrough))
        assert stripped == [
            "items-update-status", "YOK-1", "status", "implementing",
        ]

    def test_no_separator_is_a_noop(self) -> None:
        ns = watch_lifecycle._parse_args(
            ["items-update-status", "YOK-1", "status", "implementing"]
        )
        stripped = watch_lifecycle._strip_separator(list(ns.passthrough))
        assert stripped == [
            "items-update-status", "YOK-1", "status", "implementing",
        ]


def _run_fake_lifecycle(tmp_path, code: str):
    raw = tmp_path / "raw.log"
    progress = tmp_path / "progress.log"
    rc = _watch_runner.run_watcher(
        argv=[sys.executable, "-c", code],
        classifier=watch_lifecycle.classify_lifecycle_line,
        raw_capture=raw,
        progress_capture=progress,
        kind=watch_lifecycle.KIND,
        stdout_stream=io.StringIO(),
    )
    return rc, progress


class TestExitCodePassthrough:
    """The wrapper preserves the underlying engine's exit code."""

    def test_zero_exit_is_passed_through(self, tmp_path):
        rc, _progress = _run_fake_lifecycle(
            tmp_path,
            "print('=== Done transition: YOK-1 ==='); print('Status verified: done')",
        )
        assert rc == 0

    def test_nonzero_exit_is_passed_through(self, tmp_path):
        rc, _progress = _run_fake_lifecycle(
            tmp_path,
            "import sys; print('Error: bad', file=sys.stderr); sys.exit(11)",
        )
        assert rc == 11


class TestSentinelAutoExit:
    """The wrapper writes the progress-capture exit sentinel."""

    def test_exit_sentinel_emitted(self, tmp_path):
        rc, progress = _run_fake_lifecycle(
            tmp_path,
            "print('--- Populating merged_at (pre-flight) ---')",
        )
        assert rc == 0
        progress_text = progress.read_text(encoding="utf-8")
        progress_lines = [
            line for line in progress_text.splitlines() if line.strip()
        ]
        assert progress_lines[-1].startswith("# watch_lifecycle exit=0")
