"""Repo contracts name each failure and the recipe that repairs it."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.tools import ci_repo_contracts as crc
from yoke_harness.git_hooks import file_line_check as flc


def test_authored_file_limit_failure_names_each_file_and_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grown = SimpleNamespace(path="runtime/big.py", new_line_count=353)
    monkeypatch.setattr(
        flc,
        "changed_files_check",
        lambda **_kw: SimpleNamespace(
            ok=False,
            summary="1 hard-fail(s), 0 warning(s)",
            hard_fails=[grown],
        ),
    )
    scope = crc.ChangedPathScope(base_sha="0" * 40, paths=())

    ok, detail = crc.check_authored_file_limit(Path("."), scope)

    assert ok is False
    assert f"runtime/big.py: 353 lines, limit {flc.LIMIT}" in detail


def test_install_bundle_tree_failure_names_the_sync_recipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoke_core.domain import install_bundle_tree_sync
    from yoke_core.tools._source_pythonpath import INSTALL_BUNDLE_SYNC_RECIPE

    monkeypatch.setattr(
        install_bundle_tree_sync, "detect_drift", lambda **_kw: ["AGENTS.md"]
    )
    scope = crc.ChangedPathScope(base_sha="0" * 40, paths=())

    ok, detail = crc.check_install_bundle_tree(Path("."), scope)

    assert ok is False
    assert INSTALL_BUNDLE_SYNC_RECIPE in detail
