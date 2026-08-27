"""The retired path-resolution helper must stay on the obsoleted-term roster."""

from __future__ import annotations

from pathlib import Path

from yoke_project_checks.check_obsoleted_terms import scan_repo


def _retired_helper() -> str:
    return "resolve" + "_db_path"


def test_scan_detects_retired_path_resolution_helper(tmp_path: Path) -> None:
    (tmp_path / "packages").mkdir()
    (tmp_path / "packages" / "stale.py").write_text(
        f"from x import {_retired_helper()}\n"
    )
    hits = scan_repo(tmp_path)
    assert any(_retired_helper() in hit for hit in hits), hits
