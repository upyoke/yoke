"""Tests for HC-installer-live-tui-import-boundary."""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines import (
    doctor_hc_installer_live_tui_import_boundary as hc,
)


def _write(root: Path, relpath: str, text: str) -> Path:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_outside_importer_fails_for_supported_import_shapes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/yoke-core/src/yoke_core/domain/direct.py",
        "from yoke_core.tools.installer_live_tui_runner import run_remote_sequence\n",
    )
    _write(
        tmp_path,
        "packages/yoke-core/src/yoke_core/domain/package_import.py",
        "from yoke_core.tools import installer_live_tui_coordinator as coordinator\n",
    )
    _write(
        tmp_path,
        "runtime/api/engines/import_module.py",
        "import yoke_core.tools.installer_live_tui_capture as capture\n",
    )

    findings = hc.scan_installer_live_tui_import_boundary(tmp_path)

    assert {(f.relpath, f.line_no) for f in findings} == {
        ("packages/yoke-core/src/yoke_core/domain/direct.py", 1),
        ("packages/yoke-core/src/yoke_core/domain/package_import.py", 1),
        ("runtime/api/engines/import_module.py", 1),
    }


def test_family_self_import_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/yoke-core/src/yoke_core/tools/installer_live_tui_coordinator.py",
        "from yoke_core.tools import installer_live_tui_runner as runner\n",
    )

    assert hc.scan_installer_live_tui_import_boundary(tmp_path) == []


def test_family_own_test_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "runtime/api/tools/test_installer_live_tui_runner.py",
        "from yoke_core.tools import installer_live_tui_runner as runner\n",
    )

    assert hc.scan_installer_live_tui_import_boundary(tmp_path) == []


def test_clean_tree_passes(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/yoke-core/src/yoke_core/domain/clean.py",
        "# from yoke_core.tools import installer_live_tui_runner\n"
        "def handle(request):\n"
        "    return request\n",
    )

    assert hc.scan_installer_live_tui_import_boundary(tmp_path) == []
