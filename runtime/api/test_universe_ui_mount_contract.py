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


def _run_javascript_tests(test_modules: list[Path]) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is unavailable for the vanilla-JS contract test")
    completed = subprocess.run(
        [
            node, "--test", "--test-concurrency=8", "--test-reporter=tap",
            *map(str, test_modules),
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, (
        f"{completed.stdout}\n{completed.stderr}"
    )


def test_universe_ui_javascript_modules_in_node() -> None:
    # One pytest case keeps xdist from launching the entire suite per worker.
    _run_javascript_tests(_javascript_test_modules())


def test_javascript_failure_names_file_and_test(tmp_path: Path) -> None:
    failing_module = tmp_path / "deliberate_failure.test.mjs"
    failing_module.write_text(
        "import { test } from 'node:test';\n"
        "test('deliberate contract failure', () => {\n"
        "  throw new Error('failure diagnostic probe');\n"
        "});\n"
    )
    with pytest.raises(AssertionError) as failure:
        _run_javascript_tests([failing_module])
    assert failing_module.name in str(failure.value)
    assert "deliberate contract failure" in str(failure.value)
