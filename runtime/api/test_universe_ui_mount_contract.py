"""Execute the dependency-free JavaScript tests for the universe UI."""

from __future__ import annotations

import json
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
            node, "--experimental-vm-modules",
            str(Path(__file__).with_name("run_javascript_contracts.mjs")),
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
    assert "failure diagnostic probe" in str(failure.value)


def test_javascript_modules_share_process_and_isolate_globals(tmp_path: Path) -> None:
    pids = tmp_path / "processes.txt"
    (tmp_path / "counter.mjs").write_text(
        "let count = 0; export const next = () => ++count;\n"
    )
    modules = []
    for owner in range(2):
        module = tmp_path / f"isolated_{owner}.test.mjs"
        module.write_text(
            "import { after, test } from 'node:test';\n"
            "import assert from 'node:assert/strict';\n"
            "import { appendFileSync } from 'node:fs';\n"
            "import { next } from './counter.mjs';\n"
            "assert.equal(globalThis.owner, undefined);\n"
            f"globalThis.owner = {owner};\n"
            f"after(() => assert.equal(globalThis.owner, {owner}));\n"
            "test('isolated globals', (t) => {\n"
            "  const timer = setInterval(() => {}, 60000);\n"
            "  t.after(() => clearInterval(timer));\n"
            f"  assert.equal(globalThis.owner, {owner});\n"
            "  assert.equal(next(), 1);\n"
            f"  appendFileSync({json.dumps(str(pids))}, `${{process.pid}}\\n`);\n"
            "});\n"
        )
        modules.append(module)
    _run_javascript_tests(modules)
    process_ids = pids.read_text().splitlines()
    assert len(process_ids) == len(modules)
    assert len(set(process_ids)) == 1
