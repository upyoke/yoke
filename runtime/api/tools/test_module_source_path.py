"""Tests for the module source-path diagnostic helper."""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import module_source_path


def test_resolve_module_source_path_returns_package_origin() -> None:
    path = module_source_path.resolve_module_source_path("yoke_core")

    assert path is not None
    assert Path(path).name == "__init__.py"
    assert "yoke_core" in Path(path).parts


def test_main_prints_resolved_path(capsys) -> None:
    rc = module_source_path.main(["yoke_core"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "yoke_core" in out


def test_main_returns_nonzero_for_missing_module(capsys) -> None:
    rc = module_source_path.main(["not_a_real_yoke_module_name"])

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert "module not found" in captured.err
