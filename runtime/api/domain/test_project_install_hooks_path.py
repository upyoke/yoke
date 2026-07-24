"""Tests for the install-time hooksPath / PATH shadow warnings.

The helper is exercised directly (the full copy-install runner resolves a
bundle over HTTPS, which these unit tests deliberately avoid): core.hooksPath
resolution and the `yoke`-on-PATH probe are monkeypatched so each shadowing
condition is asserted in isolation.
"""

from __future__ import annotations

from yoke_cli.project_install import hooks_path_check
from yoke_cli.project_install.hooks_path_check import collect_hooks_path_warnings


def _patch(monkeypatch, core_hooks_path, yoke_on_path) -> None:
    monkeypatch.setattr(
        hooks_path_check, "_core_hooks_path", lambda root: core_hooks_path,
    )
    monkeypatch.setattr(
        hooks_path_check.shutil, "which",
        lambda name: "/usr/local/bin/yoke" if yoke_on_path else None,
    )


def test_no_warnings_when_unset_and_yoke_on_path(tmp_path, monkeypatch) -> None:
    _patch(monkeypatch, None, True)
    assert collect_hooks_path_warnings(tmp_path) == []


def test_warns_when_core_hooks_path_shadows(tmp_path, monkeypatch) -> None:
    _patch(monkeypatch, "/somewhere/else/hooks", True)
    warnings = collect_hooks_path_warnings(tmp_path)
    assert len(warnings) == 1
    assert "core.hooksPath" in warnings[0]
    assert "shadowed" in warnings[0]


def test_no_shadow_warning_when_pointing_at_default(tmp_path, monkeypatch) -> None:
    default = tmp_path / ".git" / "hooks"
    _patch(monkeypatch, str(default), True)
    assert collect_hooks_path_warnings(tmp_path) == []


def test_warns_when_yoke_not_on_path(tmp_path, monkeypatch) -> None:
    _patch(monkeypatch, None, False)
    warnings = collect_hooks_path_warnings(tmp_path)
    assert len(warnings) == 1
    assert "yoke" in warnings[0].lower()
    assert "PATH" in warnings[0]


def test_both_conditions_produce_two_warnings(tmp_path, monkeypatch) -> None:
    _patch(monkeypatch, "/foreign/hooks", False)
    warnings = collect_hooks_path_warnings(tmp_path)
    assert len(warnings) == 2
