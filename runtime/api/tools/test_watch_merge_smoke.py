"""watch merge smoke regression coverage."""

# ruff: noqa: F401
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
import pytest
from yoke_core.tools import watch_merge
from yoke_core.tools._watch_runner import filter_match

from runtime.api.tools.test_watch_merge import (
    DONE_TRANSITION_FIXTURE_LINES,
    FAKE_ITEM,
    FAKE_ITEM_NUM,
    MERGE_WORKTREE_FIXTURE_LINES,
    NOISE_LINES,
    PRIMARY_ITEM,
    PRIMARY_ITEM_NUM,
    SECONDARY_ITEM,
    SECONDARY_ITEM_NUM,
    pytestmark,
)


class TestLiveWrapperSmokeViaPython:
    def test_split_capture_against_python_one_liner(self, tmp_path: Path) -> None:
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
            f"{tmp_path}{os.pathsep}{yoke_root}{os.pathsep}{env.get('PYTHONPATH', '')}"
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
                    "kind='merge', outcome_only=True);"
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
        # Routine progress stays in raw, while errors and the final result
        # reach the user-facing capture.
        assert f"=== Done transition: {FAKE_ITEM} ===" not in progress_text
        assert "Error: synthetic failure" in progress_text
        assert "# watch_merge outcome: completed successfully" in progress_text
        # Title detail is intentionally below the filter — appears only in raw.
        assert "Title: ignored detail" in raw_text
        assert "Title: ignored detail" not in progress_text
        # Footer with exit code present.
        assert "exit=0" in progress_text
