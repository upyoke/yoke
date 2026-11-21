"""The product smoke runner starts from a bare checkout with plain Python.

CI runs ``python runtime/api/tools/product_runner_smoke.py`` before any Yoke
package is installed, so every import above the runner's own path setup must
come from the standard library. ``-E -s -S`` drops PYTHONPATH, user site and
site-packages (where the test environment installed ``yoke_contracts``) while
keeping the script directory on ``sys.path`` exactly as CI's start does.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "runtime/api/tools/product_runner_smoke.py"


def plain_start(script: Path) -> subprocess.CompletedProcess[str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("PYTHON")
    }
    return subprocess.run(
        [sys.executable, "-E", "-s", "-S", str(script), "--help"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_runner_starts_without_installed_packages():
    completed = plain_start(RUNNER)
    assert "ModuleNotFoundError" not in completed.stderr, completed.stderr
    assert completed.returncode == 0, completed.stderr
    assert "--output" in completed.stdout


def test_an_import_above_the_path_setup_fails_the_start(tmp_path):
    source = RUNNER.read_text(encoding="utf-8")
    planted = source.replace(
        "import argparse\n",
        "from yoke_contracts.venv_layout import venv_console_script\n\nimport argparse\n",
        1,
    )
    assert planted != source
    # Beside the real runner so its sibling imports and path setup still resolve.
    script = RUNNER.with_name(f"_planted_smoke_{os.getpid()}.py")
    script.write_text(planted, encoding="utf-8")
    try:
        completed = plain_start(script)
    finally:
        script.unlink()
    assert completed.returncode != 0
    assert "No module named 'yoke_contracts'" in completed.stderr
