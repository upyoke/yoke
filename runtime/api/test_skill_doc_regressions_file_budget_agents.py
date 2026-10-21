"""File Budget contract: the canonical line checker module exists."""

from __future__ import annotations

from pathlib import Path


def test_canonical_checker_module_exists():
    from yoke_core.domain import file_line_check

    path = Path(file_line_check.__file__).resolve()
    assert path.is_file(), f"canonical checker missing: {path}"
