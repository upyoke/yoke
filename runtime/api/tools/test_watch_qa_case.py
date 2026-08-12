"""Tests for ``yoke_core.tools.watch_qa_case``.

Covers the gate-run line classifier against representative output (CI
workflow polls, the restated outcome, the result envelope, engine
failures), the delegation to the pytest classifier that a locally
executed case relies on, the nested-invocation rejection, the
passthrough contract, and the one property the wrapper exists for: a
kind that the exit sentinel — and therefore an armed Monitor — can
actually match.
"""

from __future__ import annotations

import io
import os
import shlex
from contextlib import redirect_stdout

import pytest

from yoke_core.tools import watch_qa_case
from yoke_core.tools._watch_runner import filter_match
from yoke_core.tools._watch_throttle import LineClass
from yoke_core.tools.watch_tail import EXIT_SENTINEL


class TestGateClassifier:
    @pytest.mark.parametrize(
        "line",
        [
            "  Workflow status: waiting (elapsed: 0s, next poll: 5s)",
            "  Workflow status: in_progress (elapsed: 375s, next poll: 30s)",
            "Workflow status: queued (elapsed: 16s, next poll: 20s)",
        ],
    )
    def test_workflow_polls_are_progress(self, line: str) -> None:
        assert watch_qa_case.classify_qa_case_line(line).cls is LineClass.PROGRESS

    @pytest.mark.parametrize(
        "line",
        [
            "# qa case run: verdict=pass outcome=passed exit_code=0",
            "# qa case run: verdict=fail outcome=failed exit_code=1 capture=/x.log",
            '{"artifact_id": 1, "exit_code": 0, "verdict": "pass"}',
        ],
    )
    def test_outcome_and_envelope_are_summary(self, line: str) -> None:
        assert watch_qa_case.classify_qa_case_line(line).cls is LineClass.SUMMARY

    @pytest.mark.parametrize(
        "line",
        [
            "yoke qa case run: this Command case requires --base-url",
            "qa case run TREE-BINDING REFUSAL: session s holds a work-claim",
            "GitHub Actions status relay is temporarily unavailable; retrying",
        ],
    )
    def test_failures_and_degraded_relay_are_urgent(self, line: str) -> None:
        assert watch_qa_case.classify_qa_case_line(line).cls is LineClass.URGENT

    @pytest.mark.parametrize(
        "line",
        [
            "  resolving requirement...",
            "irrelevant noise",
            "",
        ],
    )
    def test_unrecognized_lines_are_noise(self, line: str) -> None:
        assert watch_qa_case.classify_qa_case_line(line).cls is LineClass.NOISE


class TestPytestDelegation:
    """A locally executed case streams its command's output verbatim.

    That command is usually pytest, so its lines must keep classifying
    rather than sink to NOISE — and they must do so through the pytest
    classifier, not a second copy of its regexes.
    """

    def test_pytest_progress_still_classifies(self) -> None:
        line = "........................................ [ 47%]"
        assert watch_qa_case.classify_qa_case_line(line).cls is LineClass.PROGRESS

    def test_pytest_failure_still_classifies(self) -> None:
        line = "FAILED tests/test_thing.py::test_case - AssertionError"
        assert watch_qa_case.classify_qa_case_line(line).cls is LineClass.URGENT

    def test_pytest_summary_still_classifies(self) -> None:
        line = "==================== 12 passed in 3.20s ====================="
        assert watch_qa_case.classify_qa_case_line(line).cls is LineClass.SUMMARY


class TestUnionPattern:
    def test_each_class_matches_the_union(self) -> None:
        for line in (
            "  Workflow status: waiting (elapsed: 0s, next poll: 5s)",
            "# qa case run: verdict=pass outcome=passed exit_code=0",
            "yoke qa case run: boom",
        ):
            assert filter_match(watch_qa_case.QA_CASE_PROGRESS_PATTERN, line)


class TestSentinelMatchableKind:
    """The kind must satisfy the sentinel regex an armed Monitor waits on.

    ``watch_tail`` exits on ``^# watch_<kind> exit=<rc>`` where ``<kind>``
    is ``\\w+``. A hyphenated kind would still produce captures and still
    look correct in the streaming pair, while leaving every armed Monitor
    running forever — which is the failure this wrapper was written to
    remove.
    """

    def test_kind_produces_a_matchable_sentinel(self) -> None:
        assert EXIT_SENTINEL.match(f"# watch_{watch_qa_case.KIND} exit=0")

    def test_kind_matches_a_signal_killed_exit(self) -> None:
        assert EXIT_SENTINEL.match(f"# watch_{watch_qa_case.KIND} exit=-15")


class TestNestedInvocationRejection:
    @pytest.mark.parametrize(
        "args",
        [
            ["python3", "-m", "yoke_core.domain.qa_case_execution_cli"],
            ["python", "-m", "yoke_core.domain.qa_case_execution_cli", "--x"],
            ["/usr/bin/python3", "-m", "yoke_core.domain.qa_case_execution_cli"],
            ["sys.executable", "-m", "yoke_core.domain.qa_case_execution_cli"],
            # The likelier paste: the command as the operator types it.
            ["yoke", "qa", "case", "run", "--requirement-id", "1"],
        ],
    )
    def test_restated_command_detected(self, args: list[str]) -> None:
        assert watch_qa_case._is_nested_invocation(args)

    @pytest.mark.parametrize(
        "args",
        [
            ["--requirement-id", "1"],
            [],
            ["python3", "-m", "pytest"],
            ["yoke", "qa", "requirement", "list"],
        ],
    )
    def test_plain_flags_pass(self, args: list[str]) -> None:
        assert not watch_qa_case._is_nested_invocation(args)

    def test_main_rejects_before_starting_a_process(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = watch_qa_case.main(["--", "yoke", "qa", "case", "run"])
        assert rc == 2
        assert "do not include the command itself" in capsys.readouterr().err


class TestCaseRunArgv:
    def test_argv_includes_module_prefix(self) -> None:
        import sys

        argv = watch_qa_case._case_run_argv(["--requirement-id", "7"])
        assert argv[0] == sys.executable
        assert argv[1:3] == ["-m", "yoke_core.domain.qa_case_execution_cli"]
        assert argv[3:] == ["--requirement-id", "7"]


class TestPassthroughParsing:
    def test_canonical_separator_form_forwards(self) -> None:
        ns, passthrough = watch_qa_case._parse_args(["--", "--requirement-id", "7"])
        assert ns.print_streaming_pair is False
        assert passthrough == ["--requirement-id", "7"]

    def test_bare_and_separator_forms_are_identical(self) -> None:
        _, bare = watch_qa_case._parse_args(["--requirement-id", "7"])
        _, separator = watch_qa_case._parse_args(["--", "--requirement-id", "7"])
        assert bare == separator

    def test_wrapper_flag_consumed_in_bare_mix(self) -> None:
        ns, passthrough = watch_qa_case._parse_args(
            ["--print-streaming-pair", "--requirement-id", "7"]
        )
        assert ns.print_streaming_pair is True
        assert passthrough == ["--requirement-id", "7"]

    def test_empty_argv_produces_empty_passthrough(self) -> None:
        ns, passthrough = watch_qa_case._parse_args([])
        assert ns.print_streaming_pair is False
        assert passthrough == []


class TestArgparseHelpExample:
    def test_help_teaches_the_canonical_form(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as excinfo:
            watch_qa_case._parse_args(["--help"])
        assert excinfo.value.code == 0
        assert "yoke watch qa-case -- --requirement-id" in capsys.readouterr().out


class TestPrintStreamingPair:
    def _capture_pair(self, argv: list[str]) -> str:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = watch_qa_case.main(argv)
        assert rc == 0
        return buffer.getvalue()

    def test_pair_names_the_cli_form_and_its_tail(self) -> None:
        rendered = self._capture_pair(
            ["--print-streaming-pair", "--", "--requirement-id", "7"]
        )
        command_anchor = f"cd {shlex.quote(os.getcwd())} && yoke watch"
        assert f"{command_anchor} qa-case" in rendered
        # The paired tail is what auto-exits; a pair without it is the
        # hand-authored fallback again.
        assert f"{command_anchor} tail" in rendered
        assert " -- --requirement-id 7" in rendered

    def test_bare_form_normalizes_to_canonical(self) -> None:
        rendered = self._capture_pair(
            ["--print-streaming-pair", "--requirement-id", "7"]
        )
        assert " -- --requirement-id 7" in rendered


class TestRegistration:
    """A wrapper nobody can invoke is the gap this item closes."""

    def test_exposed_as_a_yoke_watch_subcommand(self) -> None:
        from yoke_contracts.watch_cli_forms import cli_form

        assert cli_form(watch_qa_case.WRAPPER_MODULE) == "yoke watch qa-case"

    def test_entry_point_roster_resolves_its_main(self) -> None:
        from yoke_core.tools.watch_entrypoints import WRAPPER_MAINS

        assert WRAPPER_MAINS[watch_qa_case.WRAPPER_MODULE] is watch_qa_case.main

    def test_cli_usage_line_present(self) -> None:
        from yoke_cli.commands.watchers import TOOL_SHAPED_USAGE

        assert "yoke watch qa-case" in TOOL_SHAPED_USAGE
