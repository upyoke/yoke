"""The CI watcher's line classification and registration.

Waiting on CI is long and mostly quiet, so the filter has to carry both
halves of the signal: enough progress that silence is not
indistinguishable from a hang, and every shape that ends the wait —
including the two that end it without a conclusion.
"""

from __future__ import annotations

import pytest

from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS, cli_form
from yoke_core.tools import watch_ci_run
from yoke_core.tools._watch_throttle import LineClass
from yoke_core.tools.watch_entrypoints import WRAPPER_MAINS


def _line_class(line: str) -> LineClass:
    return watch_ci_run.classify_ci_run_line(line).cls


@pytest.mark.parametrize(
    "line",
    [
        "Error: failed to read runs for abc: connection reset",
        "CI run not found: no run for abc appeared within 90s",
        "CI run timeout: 1 run(s) still running after 1800s",
    ],
)
def test_every_shape_that_ends_a_wait_without_a_verdict_is_urgent(line):
    """These are the outcomes an operator must not have to go looking for."""
    assert _line_class(line) == LineClass.URGENT


@pytest.mark.parametrize(
    "line",
    [
        "CI run target: repo=o/n sha=abc ref=HEAD workflow=yoke-ci",
        "CI run concluded: yoke-ci #1 failure (elapsed: 700s) https://e/1",
        "CI run verdict: all 2 run(s) succeeded",
    ],
)
def test_the_target_and_conclusions_are_summary(line):
    assert _line_class(line) == LineClass.SUMMARY


@pytest.mark.parametrize(
    ("line", "elapsed"),
    [
        ("CI run status: yoke-ci #1 in_progress (elapsed: 407s) https://e/1", 407.0),
        ("CI run has not appeared yet (elapsed: 60s, appearance timeout: 90s)", 60.0),
    ],
)
def test_waiting_lines_are_progress_carrying_their_elapsed_seconds(line, elapsed):
    """Elapsed is the monotonic quantity a CI wait emits.

    Handing it to the throttle lets repetitive ticks coalesce the way a
    percentage does for a test run.
    """
    classification = watch_ci_run.classify_ci_run_line(line)
    assert classification.cls == LineClass.PROGRESS
    assert classification.progress_value == elapsed


def test_unremarkable_output_is_noise():
    assert _line_class("Resolved project auth for owner/name") == LineClass.NOISE


def test_a_quoted_error_inside_a_run_title_does_not_read_as_a_banner():
    line = "CI run concluded: Error: handling #4 success (elapsed: 3s)"
    assert _line_class(line) == LineClass.SUMMARY


def test_the_union_pattern_matches_every_classified_shape():
    """The public pattern and the classifier cannot disagree."""
    for line in (
        "Error: failed to read runs",
        "CI run not found: no run for abc appeared within 90s",
        "CI run target: repo=o/n sha=abc ref=HEAD workflow=(any)",
        "CI run concluded: yoke-ci #1 success (elapsed: 3s)",
        "CI run status: yoke-ci #1 queued (elapsed: 0s)",
        "CI run has not appeared yet (elapsed: 0s, appearance timeout: 90s)",
    ):
        assert watch_ci_run.CI_RUN_PROGRESS_PATTERN.search(line), line


def test_the_wrapper_drives_the_commit_run_watch():
    """Drift here would mean the watcher runs something else entirely."""
    assert watch_ci_run.ENGINE_MODULE == (
        "yoke_core.domain.github_actions_commit_run_watch"
    )
    import importlib

    assert importlib.import_module(watch_ci_run.ENGINE_MODULE) is not None


def test_the_wrapper_is_reachable_from_both_registries():
    """A wrapper nothing routes to is a wrapper that gets bypassed."""
    assert watch_ci_run.WRAPPER_MODULE in WRAPPER_MAINS
    assert WRAPPER_MAINS[watch_ci_run.WRAPPER_MODULE] is watch_ci_run.main
    assert WATCH_CLI_TOKENS[watch_ci_run.WRAPPER_MODULE] == ("watch", "ci-run")
    assert cli_form(watch_ci_run.WRAPPER_MODULE) == "yoke watch ci-run"


def test_the_cli_adapter_carries_a_usage_line():
    from yoke_cli.commands import watchers

    assert ("watch", "ci-run") in watchers.TOOL_SHAPED_SUBCOMMANDS
    assert "yoke watch ci-run" in watchers.TOOL_SHAPED_USAGE


def test_the_streaming_pair_mints_captures_without_running_anything(capsys):
    """The pair is printed from any position of the flag."""
    assert watch_ci_run.main(["--print-streaming-pair", "--", "HEAD"]) == 0
    printed = capsys.readouterr().out
    assert "yoke watch tail" in printed
    assert "watch_ci_run" in printed or "watch ci-run" in printed


def test_the_streaming_pair_flag_is_honoured_after_the_separator(capsys):
    """REMAINDER would otherwise forward it to the engine."""
    assert watch_ci_run.main(["--", "HEAD", "--print-streaming-pair"]) == 0
    assert "yoke watch tail" in capsys.readouterr().out


def test_the_watcher_is_taught_in_the_inventory():
    """A watcher the inventory does not know gets hand-authored again."""
    from yoke_core.tools import watch_inventory

    assert "watch_ci_run" in watch_inventory.FALLBACK_TOKENS
    assert (
        "packages/yoke-core/src/yoke_core/tools/watch_ci_run.py"
        in watch_inventory.EXCLUDE_PATHS
    )


def test_the_packet_teaches_the_command():
    from yoke_core.domain.schema_api_context_commands_watchers import (
        WATCHERS_COMMANDS,
    )

    recipes = [entry for entry in WATCHERS_COMMANDS if "ci-run" in entry["recipe"]]
    assert len(recipes) == 1
    assert "git rev-parse" in recipes[0]["notes"]
