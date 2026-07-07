"""Tests for ``yoke_core.tools.watch_session_offer``.

Covers the line classifier against representative session-offer output
fixtures (final JSON envelope, narrative banners, error/usage lines,
noise), the nested-invocation rejection path, position-tolerant
``--`` separator parsing, exit-code passthrough, and the sentinel-driven
auto-exit.
"""

from __future__ import annotations

import io
import sys

import pytest

from yoke_core.tools import _watch_runner, watch_session_offer
from yoke_core.tools._watch_runner import filter_match
from yoke_core.tools._watch_throttle import LineClass


class TestSessionOfferClassifier:
    @pytest.mark.parametrize(
        "line",
        [
            "HarnessSessionOffered: session_id=abc step=1",
            "NextActionChosen: action=charge correlation_id=xyz",
            "SchedulerOfferSkipped: refreshed_in_place",
            "SessionOfferLaneOverrideIgnored: primary != DARIUS",
            "=== session-offer decision: charge ===",
            '{"action": "charge", "reason": "15 runnable", "chainable": true}',
            '{"action": "wait", "reason": "frontier empty", "chainable": false}',
            '{"action": "escalate", "reason": "blocked", "chainable": false}',
        ],
    )
    def test_summary_lines_classify(self, line: str) -> None:
        cls = watch_session_offer.classify_session_offer_line(line)
        assert cls.cls is LineClass.SUMMARY

    @pytest.mark.parametrize(
        "line",
        [
            "Error: session-offer for executor 'foo' requires …",
            "ERROR: failed to acquire claim",
            "Usage: session-offer --executor E --provider P --workspace W",
            "Warning: lane override ignored",
        ],
    )
    def test_urgent_lines_classify(self, line: str) -> None:
        cls = watch_session_offer.classify_session_offer_line(line)
        assert cls.cls is LineClass.URGENT

    @pytest.mark.parametrize(
        "line",
        [
            "  resolving DB path...",
            "irrelevant noise",
            "some debug output",
            "",
            '{"item_id": 1}',  # not a session-offer envelope
        ],
    )
    def test_noise_lines_classify(self, line: str) -> None:
        cls = watch_session_offer.classify_session_offer_line(line)
        assert cls.cls is LineClass.NOISE


class TestUnionPattern:
    def test_summary_lines_match_union(self) -> None:
        for line in (
            "HarnessSessionOffered",
            "NextActionChosen",
            '{"action": "charge"}',
            "=== session-offer ===",
        ):
            assert filter_match(
                watch_session_offer.SESSION_OFFER_PROGRESS_PATTERN, line,
            )

    def test_urgent_lines_match_union(self) -> None:
        for line in (
            "Error: bad",
            "Usage: session-offer",
            "Warning: lane override",
        ):
            assert filter_match(
                watch_session_offer.SESSION_OFFER_PROGRESS_PATTERN, line,
            )


class TestNestedSessionOfferRejection:
    @pytest.mark.parametrize(
        "args",
        [
            ["python3", "-m", "yoke_core.api.service_client", "session-offer"],
            [
                "python3", "-m", "yoke_core.api.service_client",
                "session-offer", "--executor", "claude-code",
            ],
            ["python", "-m", "yoke_core.api.service_client", "session-offer"],
            [
                "/usr/bin/python3", "-m", "yoke_core.api.service_client",
                "session-offer",
            ],
            [
                "sys.executable", "-m", "yoke_core.api.service_client",
                "session-offer",
            ],
        ],
    )
    def test_nested_invocation_detected(self, args: list[str]) -> None:
        assert watch_session_offer._is_nested_session_offer_invocation(args)

    @pytest.mark.parametrize(
        "args",
        [
            ["--executor", "claude-code"],
            ["--executor", "claude-code", "--provider", "anthropic"],
            [],
            # service_client without the session-offer subcommand
            ["python3", "-m", "yoke_core.api.service_client", "session-heartbeat"],
            # other subcommands
            ["python3", "-m", "yoke_core.cli.db_router"],
        ],
    )
    def test_non_nested_invocations_pass(self, args: list[str]) -> None:
        assert not watch_session_offer._is_nested_session_offer_invocation(args)


class TestSessionOfferArgv:
    def test_argv_includes_module_and_subcommand(self) -> None:
        argv = watch_session_offer._session_offer_argv([
            "--executor", "claude-code", "--workspace", "/repo",
        ])
        assert argv[0] == sys.executable
        assert argv[1:] == [
            "-m", "yoke_core.api.service_client", "session-offer",
            "--executor", "claude-code", "--workspace", "/repo",
        ]


class TestPrintStreamingPair:
    def test_print_streaming_pair_emits_three_line_block(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = watch_session_offer.main([
            "--print-streaming-pair", "--",
            "--executor", "claude-code", "--workspace", "/repo",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "yoke_core.tools.watch_session_offer" in out
        assert "--raw-capture" in out
        assert "--progress-capture" in out
        assert "--executor claude-code" in out
        assert "yoke_core.tools.watch_tail" in out
        assert "tail -80" in out

    def test_print_streaming_pair_flag_position_tolerant(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = watch_session_offer.main([
            "--", "--executor", "claude-code", "--print-streaming-pair",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "yoke_core.tools.watch_session_offer" in out
        assert "--executor claude-code" in out


class TestPassthroughSeparator:
    def test_leading_separator_is_stripped(self) -> None:
        ns = watch_session_offer._parse_args(
            ["--", "--executor", "claude-code"]
        )
        stripped = watch_session_offer._strip_separator(list(ns.passthrough))
        assert stripped == ["--executor", "claude-code"]

    def test_strip_separator_is_a_noop_on_clean_args(self) -> None:
        # Bare positional REMAINDER arg — no leading ``--`` to strip.
        stripped = watch_session_offer._strip_separator(["positional"])
        assert stripped == ["positional"]


class TestExitCodePassthrough:
    """The wrapper preserves session-offer's exit code. Uses real
    ``_watch_runner.run_watcher`` with a fake argv invoking a Python
    one-liner returning a chosen exit code.
    """

    def test_zero_exit_is_passed_through(self, tmp_path):
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        argv = [
            sys.executable,
            "-c",
            'print(\'{"action": "charge", "reason": "ok", '
            '"chainable": true, "correlation_id": "x"}\')',
        ]
        rc = _watch_runner.run_watcher(
            argv=argv,
            classifier=watch_session_offer.classify_session_offer_line,
            raw_capture=raw,
            progress_capture=progress,
            kind=watch_session_offer.KIND,
            stdout_stream=io.StringIO(),
        )
        assert rc == 0

    def test_nonzero_exit_is_passed_through(self, tmp_path):
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        argv = [
            sys.executable,
            "-c",
            "import sys; print('Error: bad', file=sys.stderr); sys.exit(13)",
        ]
        rc = _watch_runner.run_watcher(
            argv=argv,
            classifier=watch_session_offer.classify_session_offer_line,
            raw_capture=raw,
            progress_capture=progress,
            kind=watch_session_offer.KIND,
            stdout_stream=io.StringIO(),
        )
        assert rc == 13


class TestSentinelAutoExit:
    """The wrapper writes ``# watch_session-offer exit=<rc>`` as the
    final line of the progress capture so ``watch_tail`` auto-exits
    when the underlying command finishes.
    """

    def test_exit_sentinel_emitted(self, tmp_path):
        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"
        argv = [
            sys.executable,
            "-c",
            'print(\'{"action": "wait", "chainable": false}\')',
        ]
        rc = _watch_runner.run_watcher(
            argv=argv,
            classifier=watch_session_offer.classify_session_offer_line,
            raw_capture=raw,
            progress_capture=progress,
            kind=watch_session_offer.KIND,
            stdout_stream=io.StringIO(),
        )
        assert rc == 0
        progress_text = progress.read_text(encoding="utf-8")
        progress_lines = [
            line for line in progress_text.splitlines() if line.strip()
        ]
        # Sentinel is "# watch_session-offer exit=0" with the kind verbatim.
        assert progress_lines[-1].startswith("# watch_session-offer exit=0")
