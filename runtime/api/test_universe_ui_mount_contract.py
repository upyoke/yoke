"""Execute the dependency-free JavaScript mount-contract tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_universe_ui_mount_contract_in_node() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable for the vanilla-JS contract test")
    test_module = Path(__file__).with_name(
        "universe_ui_mount_contract.test.mjs"
    )
    completed = subprocess.run(
        [node, "--test", str(test_module)],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, (
        f"{completed.stdout}\n{completed.stderr}"
    )
