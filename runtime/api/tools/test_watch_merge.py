"""Tests for ``yoke_core.tools.watch_merge``.

Covers:
- Filter regex against representative output fixtures captured from
  ``yoke_core.engines.done_transition`` and
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

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from yoke_core.tools import watch_merge
from yoke_core.tools._watch_runner import filter_match

PRIMARY_ITEM_NUM = 42
PRIMARY_ITEM = f"YOK-{PRIMARY_ITEM_NUM}"
SECONDARY_ITEM_NUM = 99
SECONDARY_ITEM = f"YOK-{SECONDARY_ITEM_NUM}"
FAKE_ITEM_NUM = 9
FAKE_ITEM = f"YOK-{FAKE_ITEM_NUM}"

# Representative output captured by hand from the engines.
DONE_TRANSITION_FIXTURE_LINES: list[str] = [
    "YOKE_REPO_ROOT=/repo",
    "",
    f"=== Done transition: {PRIMARY_ITEM} ===",
    "Title: Some title",
    "Old status: implementing",
    "Type: issue",
    "",
    "Project: yoke (repo: /repo)",
    "Pre-flight: merge already completed (no worktree), status is 'implemented'.",
    "Resuming from step 6 (status update and post-merge steps).",
    "Branch already merged — skipping merge step.",
    f"Error: Merge of branch '{PRIMARY_ITEM}' failed.",
    "Merge halted: agent resolution required.",
    "HARD STOP: User-authored files at risk.",
    "RESULT_FILE=/tmp/result.json",
]

MERGE_WORKTREE_FIXTURE_LINES: list[str] = [
    f"Merging branch: {PRIMARY_ITEM} → main",
    f"Worktree: /repo/.worktrees/{PRIMARY_ITEM}",
    "Error: merge phase 'rebase' failed (exit 1).",
    "Error: GitHub CLI (gh) is required for merge.",
    f"Error: branch '{SECONDARY_ITEM}' does not exist as a local ref.",
    f"Warning: branch mismatch detected. Correcting to {PRIMARY_ITEM}.",
    "Merge lock error: lease held by other session.",
    "fatal: not a git repository",
]

NOISE_LINES: list[str] = [
    "  some indented detail",
    "Title: Some title",  # detail-only — should not match (no leading sentinel)
    "Old status: implementing",
    "Type: issue",
    "Project: yoke (repo: /repo)",
    "ordinary diagnostic detail",
]


class TestMergeFilterCoverage:
    @pytest.mark.parametrize("line", DONE_TRANSITION_FIXTURE_LINES)
    def test_done_transition_signal_lines_or_blank(self, line: str) -> None:
        # Each non-blank fixture line is either a section header, status
        # line, error/warning, or RESULT_FILE/YOKE_REPO_ROOT emission.
        # Blank lines are not signal — the rest are.
        if not line.strip():
            assert not filter_match(watch_merge.MERGE_PROGRESS_PATTERN, line)
            return
        # Pure context lines like "Title:", "Old status:", "Type:",
        # "Project:" are NOT in the filter — they appear under the
        # `=== Done transition: ===` banner that IS matched, and the
        # banner is sufficient to anchor operator attention.
        if any(line.startswith(prefix) for prefix in ("Title:", "Old status:", "Type:", "Project:")):
            assert not filter_match(watch_merge.MERGE_PROGRESS_PATTERN, line)
            return
        assert filter_match(watch_merge.MERGE_PROGRESS_PATTERN, line)

    @pytest.mark.parametrize("line", MERGE_WORKTREE_FIXTURE_LINES)
    def test_merge_worktree_signal_lines(self, line: str) -> None:
        assert filter_match(watch_merge.MERGE_PROGRESS_PATTERN, line)

    @pytest.mark.parametrize("noise", NOISE_LINES)
    def test_noise_lines_do_not_match(self, noise: str) -> None:
        assert not filter_match(watch_merge.MERGE_PROGRESS_PATTERN, noise)

    def test_done_transition_fixture_distinguishes_signal_from_noise(
        self,
    ) -> None:
        signal = [
            line
            for line in DONE_TRANSITION_FIXTURE_LINES
            if filter_match(watch_merge.MERGE_PROGRESS_PATTERN, line)
        ]
        joined = "\n".join(signal)
        assert "=== Done transition" in joined
        assert "Pre-flight:" in joined
        assert "Resuming from step" in joined
        assert "Branch already merged" in joined
        assert "Error:" in joined
        assert "Merge halted:" in joined
        assert "HARD STOP:" in joined
        assert "RESULT_FILE=" in joined
        assert "YOKE_REPO_ROOT=" in joined
        # Detail lines that should be skipped:
        assert "Title:" not in joined
        assert "Old status:" not in joined


class TestSubcommandResolution:
    def test_known_subcommand_returns_engine_module(self) -> None:
        module, rest = watch_merge._resolve_subcommand(
            ["done-transition", PRIMARY_ITEM]
        )
        assert module == "yoke_core.engines.done_transition"
        assert rest == [PRIMARY_ITEM]

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
        assert watch_merge._strip_separator(
            ["merge-worktree", PRIMARY_ITEM]
        ) == ["merge-worktree", PRIMARY_ITEM]

    def test_leading_separator_only(self) -> None:
        assert watch_merge._strip_separator(
            ["--", "merge-worktree", PRIMARY_ITEM]
        ) == ["merge-worktree", PRIMARY_ITEM]

    def test_inner_separator_only(self) -> None:
        assert watch_merge._strip_separator(
            ["merge-worktree", "--", PRIMARY_ITEM]
        ) == ["merge-worktree", PRIMARY_ITEM]

    def test_both_separators(self) -> None:
        assert watch_merge._strip_separator(
            ["--", "merge-worktree", "--", PRIMARY_ITEM]
        ) == ["merge-worktree", PRIMARY_ITEM]


class TestPrintStreamingPair:
    def test_print_streaming_pair_for_done_transition(
        self, capsys, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = watch_merge.main(
            ["--print-streaming-pair", "--", "done-transition", PRIMARY_ITEM]
        )
        assert rc == 0
        out = capsys.readouterr().out
        anchor = f"cd {shlex.quote(os.getcwd())} && uv run --frozen python3 -m"
        assert f"{anchor} yoke_core.tools.watch_merge" in out
        assert "PYTHONPATH" not in out
        # Sub-command argv preserved in the printed Bash invocation.
        assert "done-transition" in out
        # Progress tail auto-exits via watch_tail; post-completion inspection
        # still uses tail -80 against the raw capture.
        assert f"{anchor} yoke_core.tools.watch_tail" in out
        assert ".progress." in out
        assert "tail -80" in out
        assert ".raw." in out

    def test_print_streaming_pair_rejects_unknown_subcommand(
        self, capsys, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = watch_merge.main(
            ["--print-streaming-pair", "--", "nonsense-cmd"]
        )
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


class TestLiveWrapperSmokeViaPython:
    def test_split_capture_against_python_one_liner(
        self, tmp_path: Path
    ) -> None:
        """Use a custom argv path to verify the split-capture contract.

        ``watch_merge`` is sub-command-driven by design, but the underlying
        ``_watch_runner.run_watcher`` is a thin wrapper. We exercise the
        full live path end-to-end by invoking ``watch_merge`` itself with a
        fake ``done-transition`` shape, via a temporary engine module, so
        the test does not depend on Yoke's real DB state.
        """
        # Create a fake engine module on disk that prints lines matching
        # and not matching the merge progress pattern, then exits 0.
        fake_pkg = tmp_path / "fake_engines"
        fake_pkg.mkdir()
        (fake_pkg / "__init__.py").write_text("", encoding="utf-8")
        (fake_pkg / "fake_engine.py").write_text(
            "import sys\n"
            f"print('=== Done transition: {FAKE_ITEM} ===')\n"
            "print('Title: ignored detail')\n"
            "print('ordinary diagnostic detail')\n"
            "print('Error: synthetic failure')\n"
            "sys.exit(0)\n",
            encoding="utf-8",
        )

        raw = tmp_path / "raw.log"
        progress = tmp_path / "progress.log"

        env = os.environ.copy()
        yoke_root = Path(__file__).resolve().parents[3]
        env["PYTHONPATH"] = (
            f"{tmp_path}{os.pathsep}{yoke_root}"
            f"{os.pathsep}{env.get('PYTHONPATH', '')}"
        )

        # Drive _watch_runner.run_watcher directly because watch_merge's
        # sub-command map is intentionally closed to known engines.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from yoke_core.tools import _watch_runner, watch_merge;"
                    "import sys;"
                    f"raw = r'{raw}'; prog = r'{progress}';"
                    "rc = _watch_runner.run_watcher("
                    "argv=[sys.executable, '-m', 'fake_engines.fake_engine'],"
                    "classifier=watch_merge.classify_merge_line,"
                    "raw_capture=__import__('pathlib').Path(raw),"
                    "progress_capture=__import__('pathlib').Path(prog),"
                    "kind='merge');"
                    "sys.exit(rc)"
                ),
            ],
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, (
            f"smoke failed (exit={result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        raw_text = raw.read_text(encoding="utf-8")
        progress_text = progress.read_text(encoding="utf-8")

        # The non-matching diagnostic line lives in raw, not progress.
        assert "ordinary diagnostic detail" in raw_text
        assert "ordinary diagnostic detail" not in progress_text
        # Signal lines land in progress.
        assert f"=== Done transition: {FAKE_ITEM} ===" in progress_text
        assert "Error: synthetic failure" in progress_text
        # Title detail is intentionally below the filter — appears only in raw.
        assert "Title: ignored detail" in raw_text
        assert "Title: ignored detail" not in progress_text
        # Footer with exit code present.
        assert "exit=0" in progress_text
