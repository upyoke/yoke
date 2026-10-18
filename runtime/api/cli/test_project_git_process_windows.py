"""Native Windows drains bounded Git child pipes without socket selectors."""

from __future__ import annotations

import os
import sys

import pytest

from yoke_cli.config import project_git_process


@pytest.mark.skipif(os.name != "nt", reason="Windows pipe implementation")
def test_network_git_captures_stdout_and_stderr() -> None:
    result = project_git_process.run_network_git(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr)",
        ]
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"
