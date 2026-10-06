"""The shared approval page's interactions run in the ordinary suite."""

from pathlib import Path
import subprocess


def test_machine_approval_page_interactions():
    path = Path(__file__).with_name("universe_ui_machine_approval.test.mjs")
    result = subprocess.run(
        ["node", "--test", str(path)], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stdout + result.stderr
