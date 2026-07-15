"""Execute the dependency-free JavaScript tests for the universe UI."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def _javascript_test_modules() -> list[Path]:
    """Every `*.test.mjs` beside this file.

    Discovered rather than listed: a named roster means a new test module
    runs green on its own while the suite never calls it, which looks exactly
    like coverage that does not exist.
    """
    return sorted(Path(__file__).parent.glob("*.test.mjs"))


def test_javascript_test_modules_are_discovered() -> None:
    # Guard the guard: an empty glob would make the run below pass vacuously.
    assert _javascript_test_modules()


@pytest.mark.parametrize(
    "test_module",
    _javascript_test_modules(),
    ids=lambda path: path.name,
)
def test_universe_ui_javascript_module_in_node(test_module: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable for the vanilla-JS contract test")
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
