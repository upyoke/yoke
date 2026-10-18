"""The watcher receives child output through the platform pipe primitive."""

from __future__ import annotations

import subprocess
import sys

from yoke_core.tools.watch_child_source import ChildSource


def test_child_source_reads_lines_and_end_of_pipe() -> None:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "print('first', flush=True); print('second', flush=True)",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    lines: list[str] = []

    with ChildSource(proc.stdout) as source:
        while not source.ended:
            lines.extend(source.read(5.0) or [])

    assert proc.wait() == 0
    assert lines == ["first\n", "second\n"]
