"""Exercise native Windows collection without importing Unix-only modules."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture
def smoke(tmp_path):
    plugin = Path(__file__).resolve().parents[2] / "windows_test_selection.py"
    (tmp_path / "conftest.py").write_bytes(plugin.read_bytes())
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    windows: native Windows smoke coverage\n"
    )

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
            cwd=tmp_path,
            env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30,
        )

    return tmp_path, run


def test_windows_selection_preserves_module_and_individual_markers(smoke):
    root, run = smoke
    (root / "test_unix.py").write_text("raise ImportError('Unix-only module')\n")
    (root / "test_module.py").write_text(
        "import pytest\npytestmark = pytest.mark.windows\ndef test_module(): pass\n"
    )
    (root / "test_partial.py").write_text(
        "import pytest\n@pytest.mark.windows\ndef test_portable(): pass\n"
        "def test_unix(): assert False\n"
    )
    result = run("-m", "windows")
    assert result.returncode == 0, result.stdout
    assert "2 passed, 1 deselected" in result.stdout


def test_windows_selection_refuses_empty_suite(smoke):
    root, run = smoke
    (root / "test_unix.py").write_text("raise ImportError('Unix-only module')\n")
    result = run("--collect-only", "-m", "windows")
    assert result.returncode == pytest.ExitCode.NO_TESTS_COLLECTED, result.stdout


def test_windows_selection_keeps_selected_import_failures(smoke):
    root, run = smoke
    (root / "test_broken.py").write_text(
        "import pytest\npytestmark = pytest.mark.windows\n"
        "raise ImportError('selected module broke')\n"
    )
    result = run("--collect-only", "-m", "windows")
    assert result.returncode == pytest.ExitCode.INTERRUPTED, result.stdout
    assert "selected module broke" in result.stdout


def test_other_marker_expressions_keep_normal_collection(smoke):
    root, run = smoke
    (root / "test_normal.py").write_text("def test_normal(): pass\n")
    result = run()
    assert result.returncode == 0, result.stdout
    assert "1 passed" in result.stdout
