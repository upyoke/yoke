# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import impacted_tests

from yoke_core.tools._impacted_contract_tests import (
    DONE_TRANSITION_CLOSE_OUT_TESTS,
    WORKFLOW_DEFINITION_VALIDATION_TESTS,
)

from yoke_core.tools.impacted_tests import (
    ImportIndex,
    Selection,
    build_import_index,
    is_test_file,
    module_name_for,
    select,
)


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _with_floor(*tests: str) -> tuple[str, ...]:
    """Expected selection: the reached tests plus the always-run floor."""
    return tuple(sorted({*tests, *impacted_tests.ALWAYS_RUN_TESTS}))


def _tiny_repo(tmp_path: Path) -> Path:
    _write(tmp_path, "runtime/__init__.py", "")
    _write(tmp_path, "runtime/api/__init__.py", "")
    _write(tmp_path, "runtime/api/leaf.py", "VALUE = 1\n")
    _write(tmp_path, "runtime/api/middle.py", "from runtime.api import leaf\n")
    _write(tmp_path, "runtime/api/unrelated.py", "OTHER = 2\n")
    _write(
        tmp_path,
        "runtime/api/test_middle.py",
        "from runtime.api import middle\n\ndef test_x():\n    pass\n",
    )
    _write(
        tmp_path,
        "runtime/api/test_unrelated.py",
        "from runtime.api import unrelated\n\ndef test_y():\n    pass\n",
    )
    for test_path in impacted_tests.ALWAYS_RUN_TESTS:
        _write(tmp_path, test_path, "def test_contract(): pass\n")
    return tmp_path
