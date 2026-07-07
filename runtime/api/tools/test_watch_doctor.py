"""Tests for ``yoke_core.tools.watch_doctor``.

Covers the line classifier against representative doctor output fixtures
(per-HC PASS / FAIL / WARN / SKIP, summary banners, noise), the
nested-invocation rejection path, and the passthrough-argument contract
(canonical ``-- --quick`` form, bare-form acceptance, and the help-text
worked example).
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from yoke_core.tools import watch_doctor
from yoke_core.tools._watch_runner import filter_match
from yoke_core.tools._watch_throttle import LineClass


class TestDoctorClassifier:
    @pytest.mark.parametrize(
        "line",
        [
            "HC-foo: PASS",
            "HC-tier-schema-bleed: PASS",
            "HC-foo: WARN — non-fatal",
            "HC-foo: SKIP (no-op)",
            "  running HC-foo",
        ],
    )
    def test_progress_lines_classify(self, line: str) -> None:
        cls = watch_doctor.classify_doctor_line(line)
        assert cls.cls is LineClass.PROGRESS

    @pytest.mark.parametrize(
        "line",
        [
            "HC-foo: FAIL — broken",
            "HC-tier-schema-bleed: ERROR",
            "HC-something: fail",
        ],
    )
    def test_urgent_lines_classify(self, line: str) -> None:
        cls = watch_doctor.classify_doctor_line(line)
        assert cls.cls is LineClass.URGENT

    @pytest.mark.parametrize(
        "line",
        [
            "# Ouroboros Health Report",
            "149 checks run: 113 passed, 35 warnings, 1 failures",
            "2 checks run: 1 passed, 1 warnings, 0 failures",
        ],
    )
    def test_summary_lines_classify(self, line: str) -> None:
        cls = watch_doctor.classify_doctor_line(line)
        assert cls.cls is LineClass.SUMMARY

    @pytest.mark.parametrize(
        "line",
        [
            "Doctor report",
            "=== doctor finished ===",
            "10/12 checks passed",
            "Findings: 3",
        ],
    )
    def test_vestigial_summary_lines_no_longer_classify(self, line: str) -> None:
        # The old banner tokens never matched real doctor output;
        # the new regex MUST stop classifying them as SUMMARY so prose
        # drift back to the dead shapes is caught by this test.
        cls = watch_doctor.classify_doctor_line(line)
        assert cls.cls is LineClass.NOISE

    @pytest.mark.parametrize(
        "line",
        [
            "  resolving DB path...",
            "irrelevant noise",
            "/tmp/sun-foo.log written",
            "",
        ],
    )
    def test_noise_lines_classify(self, line: str) -> None:
        cls = watch_doctor.classify_doctor_line(line)
        assert cls.cls is LineClass.NOISE


class TestUnionPattern:
    def test_progress_lines_match_union(self) -> None:
        for line in ("HC-foo: PASS", "  running HC-bar", "HC-x: WARN"):
            assert filter_match(watch_doctor.DOCTOR_PROGRESS_PATTERN, line)

    def test_urgent_lines_match_union(self) -> None:
        for line in ("HC-foo: FAIL", "HC-bar: ERROR"):
            assert filter_match(watch_doctor.DOCTOR_PROGRESS_PATTERN, line)

    def test_summary_lines_match_union(self) -> None:
        for line in (
            "# Ouroboros Health Report",
            "149 checks run: 113 passed, 35 warnings, 1 failures",
        ):
            assert filter_match(watch_doctor.DOCTOR_PROGRESS_PATTERN, line)


class TestNestedDoctorRejection:
    @pytest.mark.parametrize(
        "args",
        [
            ["python3", "-m", "yoke_core.engines.doctor"],
            ["python3", "-m", "yoke_core.engines.doctor", "--quick"],
            ["python", "-m", "yoke_core.engines.doctor"],
            ["/usr/bin/python3", "-m", "yoke_core.engines.doctor"],
            ["sys.executable", "-m", "yoke_core.engines.doctor"],
        ],
    )
    def test_nested_invocation_detected(self, args: list[str]) -> None:
        assert watch_doctor._is_nested_doctor_invocation(args)

    @pytest.mark.parametrize(
        "args",
        [
            ["--quick"],
            ["--check", "HC-foo"],
            [],
            ["python3", "-m", "pytest"],
        ],
    )
    def test_non_nested_invocations_pass(self, args: list[str]) -> None:
        assert not watch_doctor._is_nested_doctor_invocation(args)


class TestDoctorArgv:
    def test_argv_includes_module_prefix(self) -> None:
        import sys

        argv = watch_doctor._doctor_argv(["--quick"])
        assert argv[0] == sys.executable
        assert argv[1:4] == ["-m", "yoke_core.engines.doctor", "--quick"]


class TestPassthroughParsing:
    """AC-3 / AC-6: bare doctor flags are forwarded; ``--`` separator works."""

    def test_canonical_separator_form_forwards(self) -> None:
        ns, passthrough = watch_doctor._parse_args(["--", "--quick"])
        assert ns.print_streaming_pair is False
        assert passthrough == ["--quick"]

    def test_bare_form_forwards(self) -> None:
        ns, passthrough = watch_doctor._parse_args(["--quick"])
        assert ns.print_streaming_pair is False
        assert passthrough == ["--quick"]

    def test_bare_and_separator_forms_produce_identical_passthrough(self) -> None:
        _, bare = watch_doctor._parse_args(["--quick"])
        _, separator = watch_doctor._parse_args(["--", "--quick"])
        assert bare == separator

    def test_wrapper_flag_still_consumed_in_bare_mix(self) -> None:
        ns, passthrough = watch_doctor._parse_args(
            ["--print-streaming-pair", "--quick"]
        )
        assert ns.print_streaming_pair is True
        assert passthrough == ["--quick"]

    def test_unrecognized_multiword_flags_forwarded(self) -> None:
        # Doctor's own arg-parser owns rejection of bogus flags; the
        # wrapper just forwards anything it does not consume.
        _, passthrough = watch_doctor._parse_args(["--check", "HC-foo"])
        assert passthrough == ["--check", "HC-foo"]

    def test_empty_argv_produces_empty_passthrough(self) -> None:
        ns, passthrough = watch_doctor._parse_args([])
        assert ns.print_streaming_pair is False
        assert passthrough == []


class TestArgparseHelpExample:
    """AC-1 / AC-5: argparse-rendered ``--help`` contains the worked example."""

    def test_help_contains_worked_separator_example(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            watch_doctor._parse_args(["--help"])
        assert excinfo.value.code == 0
        rendered = capsys.readouterr().out
        assert (
            "python3 -m yoke_core.tools.watch_doctor -- --quick" in rendered
        ), "argparse --help output must teach the canonical -- --quick form"

    def test_help_documents_bare_form_too(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit):
            watch_doctor._parse_args(["--help"])
        rendered = capsys.readouterr().out
        assert "python3 -m yoke_core.tools.watch_doctor --quick" in rendered


class TestPrintStreamingPair:
    """AC-2: ``--print-streaming-pair -- --quick`` emits ``-- --quick``."""

    def _capture_pair(self, argv: list[str]) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = watch_doctor.main(argv)
        assert rc == 0
        return buffer.getvalue()

    def test_streaming_pair_canonical_form(self) -> None:
        rendered = self._capture_pair(["--print-streaming-pair", "--", "--quick"])
        assert " -- --quick" in rendered

    def test_streaming_pair_bare_form_normalizes_to_canonical(self) -> None:
        # The bg command in the pair is what gets pasted into Bash; it
        # must use the canonical ``-- --quick`` shape regardless of how
        # the operator invoked --print-streaming-pair.
        rendered = self._capture_pair(["--print-streaming-pair", "--quick"])
        assert " -- --quick" in rendered

    def test_streaming_pair_empty_passthrough_keeps_separator(self) -> None:
        rendered = self._capture_pair(["--print-streaming-pair"])
        # No doctor flags forwarded — but the bg command still preserves
        # the wrapper's surface so callers can append flags later.
        assert "yoke_core.tools.watch_doctor" in rendered
