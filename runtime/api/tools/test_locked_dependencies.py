"""Shipped dependencies cannot silently leave the reviewed lock."""

from pathlib import Path

import pytest

from runtime.api.cli.test_yoke_build_release import _write_wheel
from yoke_core.tools import locked_dependencies as locked
from yoke_core.tools import build_release


@pytest.fixture
def lock(tmp_path):
    path = tmp_path / "uv.lock"
    path.write_text(
        '[manifest]\nmembers=["yoke-core"]\n'
        '[[package]]\nname="pglast"\nversion="7.20"\n'
        'source={registry="https://pypi.org/simple"}\n'
    )
    return path


def test_reports_all_changed_and_unlocked_distributions(lock):
    assert locked.version_mismatches(lock, {
        "pglast": "7.22", "unknown_dependency": "1", "yoke-core": "1",
    }.items()) == [
        "pglast: installed=7.22 locked=7.20",
        "unknown-dependency: installed=1 locked=absent from uv.lock",
    ]
    assert locked.version_mismatches(lock, [("pglast", "7.20")]) == []


def test_rejects_unlocked_wheel_bytes(lock):
    wheelhouse = lock.parent / "wheels"
    wheelhouse.mkdir()
    _write_wheel(wheelhouse, name="pglast", version="7.22")
    _write_wheel(wheelhouse, name="pglast", version="7.20")
    with pytest.raises(locked.ReleaseBuildError, match="wheelhouse_lock_mismatch.*"):
        locked.assert_locked_wheelhouse(lock.parent, wheelhouse)


def test_export_failure_does_not_yield_constraints(tmp_path):
    def fail(command, **kwargs):
        assert command[1:4] == ["export", "--locked", "--no-default-groups"]
        raise ValueError("uv lock is stale")

    with pytest.raises(ValueError, match="uv lock is stale"):
        with locked.exported_constraints(tmp_path, "uv", fail):
            pytest.fail("stale lock reached wheel resolution")


def test_export_keeps_marker_constraints_until_resolution_finishes(tmp_path):
    def export(command, **kwargs):
        Path(command[-1]).write_text("pglast==7.20\n")

    with locked.exported_constraints(tmp_path, "uv", export) as constraints:
        assert constraints.read_text() == "pglast==7.20\n"
    assert not constraints.exists()


def test_release_cli_reports_lock_mismatch_with_recovery(tmp_path, monkeypatch, capsys):
    def fail(**kwargs):
        raise locked.ReleaseBuildError(
            "wheelhouse_lock_mismatch: pglast installed=7.22 locked=7.20; rebuild from uv.lock"
        )

    monkeypatch.setattr(build_release, "build_release", fail)
    assert build_release.main([
        "--output-root", str(tmp_path), "--source-commit", "a" * 40,
    ]) == 1
    error = capsys.readouterr().err
    assert "wheelhouse_lock_mismatch" in error and "rebuild from uv.lock" in error
    assert "Traceback" not in error
