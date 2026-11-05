"""Tests for ``yoke_core.tools.watch_merge``.

Covers:
- Filter regex against representative output fixtures captured from
  ``yoke_core.engines.merge_worktree``.
- Sub-command resolution and error reporting.
- ``--print-streaming-pair`` emits an invocation pair using a known
  sub-command.
- A live subprocess smoke that runs the wrapper against a fast,
  deterministic underlying command (Python ``-c "print(...)"``) to
  confirm exit-code preservation and split capture without needing the
  real merge engines.
"""

from __future__ import annotations

from runtime.api.tools.watch_merge_test_support import (
    FAKE_ITEM as FAKE_ITEM,
    FAKE_ITEM_NUM as FAKE_ITEM_NUM,
    MERGE_WORKTREE_FIXTURE_LINES as MERGE_WORKTREE_FIXTURE_LINES,
    NOISE_LINES as NOISE_LINES,
    PRIMARY_ITEM as PRIMARY_ITEM,
    PRIMARY_ITEM_NUM as PRIMARY_ITEM_NUM,
    SECONDARY_ITEM as SECONDARY_ITEM,
    SECONDARY_ITEM_NUM as SECONDARY_ITEM_NUM,
    pytestmark as pytestmark,
)


import os
import shlex

import pytest

from yoke_core.tools import watch_merge
from yoke_core.tools._watch_runner import filter_match


# Representative output captured by hand from the engines.


class TestMergeFilterCoverage:
    @pytest.mark.parametrize("line", MERGE_WORKTREE_FIXTURE_LINES)
    def test_merge_worktree_signal_lines(self, line: str) -> None:
        if line.startswith("Warning:"):
            assert filter_match(watch_merge.MERGE_PROGRESS_PATTERN, line)
            assert watch_merge.classify_merge_line(line).cls.value == "urgent"
        else:
            assert filter_match(watch_merge.MERGE_PROGRESS_PATTERN, line)

    def test_queue_landing_poll_observations_are_signal(self) -> None:
        """A queue wait emits nothing else; the union pattern must carry it."""
        assert filter_match(
            watch_merge.MERGE_PROGRESS_PATTERN,
            "Queue landing: pull request 42: merged=false, state=open, "
            "merge-when-ready=armed, queue-entry=absent, "
            "train-run=not found (elapsed: 90s)",
        )

    @pytest.mark.parametrize("noise", NOISE_LINES)
    def test_noise_lines_do_not_match(self, noise: str) -> None:
        assert not filter_match(watch_merge.MERGE_PROGRESS_PATTERN, noise)


class TestSubcommandResolution:
    def test_known_subcommand_returns_engine_module(self) -> None:
        module, rest = watch_merge._resolve_subcommand(
            ["merge-worktree", PRIMARY_ITEM]
        )
        assert module == "yoke_cli.commands.merge_worktree_local_runtime"
        assert rest == [PRIMARY_ITEM]

    def test_merge_item_runs_the_same_entrypoint_as_the_plain_command(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The wrapper and `yoke merge item` must enter at the same place.

        That entrypoint binds this machine's GitHub user authority before
        loading the merge engine. Entering below it merges without that
        authority, which on a machine whose App credentials live
        server-side refuses the merge outright.
        """
        from types import SimpleNamespace

        from yoke_cli.commands import merge_item

        module, rest = watch_merge._resolve_subcommand(["merge-item", PRIMARY_ITEM])
        assert rest == [PRIMARY_ITEM]

        recorded: list[list[str]] = []
        monkeypatch.setattr(
            merge_item.subprocess,
            "run",
            lambda command, **kwargs: (
                recorded.append(list(command)) or SimpleNamespace(returncode=0)
            ),
        )
        merge_item.merge_item([PRIMARY_ITEM])

        assert recorded and recorded[0][1:3] == ["-m", module]

    def test_unknown_subcommand_raises_systemexit(self) -> None:
        with pytest.raises(SystemExit):
            watch_merge._resolve_subcommand(["bogus-cmd"])

    def test_missing_subcommand_raises_systemexit(self) -> None:
        with pytest.raises(SystemExit):
            watch_merge._resolve_subcommand([])


class TestStripSeparator:
    """Both leading and inner ``--`` separators get dropped.

    Without inner-separator stripping, an operator pasting
    ``watch_merge ... -- merge-worktree -- YOK-N`` (the shape
    streaming-pair output previously emitted) hands ``--`` to
    ``merge_worktree`` as its branch positional and the engine fails.
    """

    def test_no_separators(self) -> None:
        assert watch_merge._strip_separator(["merge-worktree", PRIMARY_ITEM]) == [
            "merge-worktree",
            PRIMARY_ITEM,
        ]

    def test_leading_separator_only(self) -> None:
        assert watch_merge._strip_separator(["--", "merge-worktree", PRIMARY_ITEM]) == [
            "merge-worktree",
            PRIMARY_ITEM,
        ]

    def test_inner_separator_only(self) -> None:
        assert watch_merge._strip_separator(["merge-worktree", "--", PRIMARY_ITEM]) == [
            "merge-worktree",
            PRIMARY_ITEM,
        ]

    def test_both_separators(self) -> None:
        assert watch_merge._strip_separator(
            ["--", "merge-worktree", "--", PRIMARY_ITEM]
        ) == ["merge-worktree", PRIMARY_ITEM]


class TestPrintStreamingPair:
    def test_print_streaming_pair_for_merge_item(
        self, capsys, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = watch_merge.main(
            ["--print-streaming-pair", "--", "merge-item", PRIMARY_ITEM, "--wait"]
        )
        assert rc == 0
        out = capsys.readouterr().out
        command_anchor = f"cd {shlex.quote(os.getcwd())} && yoke watch"
        assert f"{command_anchor} merge" in out
        assert "PYTHONPATH" not in out
        # Sub-command argv preserved in the printed Bash invocation.
        assert "merge-item" in out
        assert "Outcome-only stream" in out
        # Progress tail auto-exits via watch_tail; post-completion inspection
        # still uses tail -80 against the raw capture.
        assert f"{command_anchor} tail" in out
        assert ".progress." in out
        assert "tail -80" in out
        assert ".raw." in out

    def test_print_streaming_pair_rejects_unknown_subcommand(
        self, capsys, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = watch_merge.main(["--print-streaming-pair", "--", "nonsense-cmd"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "unknown sub-command" in err

    def test_print_streaming_pair_omits_inner_separator(
        self, capsys, monkeypatch, tmp_path
    ) -> None:
        """The printed Bash invocation must not contain ``-- {item}``.

        If the inner ``--`` survives into the output, an operator pasting
        the printed line invokes ``merge_worktree -- YOK-N`` and the engine
        treats ``--`` as the branch positional and exits with
        ``Error: branch '--' does not exist as a local ref``.
        """
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = watch_merge.main(
            ["--print-streaming-pair", "merge-worktree", "--", PRIMARY_ITEM]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert f"merge-worktree {PRIMARY_ITEM}" in out
        assert f"-- {PRIMARY_ITEM}" not in out
