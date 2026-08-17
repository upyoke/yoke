"""HC-runtime-module-names: shipped core modules avoid test basenames."""

from __future__ import annotations

from pathlib import Path

from yoke_core.api.repo_root import find_repo_root
from yoke_project_checks import check_runtime_module_names as hc


def _write(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("VALUE = 1\n", encoding="utf-8")


def test_current_tree_has_no_test_shaped_runtime_modules() -> None:
    repo_root = find_repo_root(Path(__file__))
    assert hc.scan_runtime_module_names(repo_root) == []


def test_test_shaped_runtime_module_is_reported(tmp_path: Path) -> None:
    runtime_root = "package"
    _write(tmp_path, f"{runtime_root}/domain/test_boot_dependency.py")

    findings = hc.scan_runtime_module_names(
        tmp_path,
        runtime_root=runtime_root,
    )

    assert [finding.relpath for finding in findings] == [
        "package/domain/test_boot_dependency.py",
    ]


def test_structural_test_and_bundle_data_surfaces_are_ignored(
    tmp_path: Path,
) -> None:
    runtime_root = "package"
    _write(tmp_path, f"{runtime_root}/tests/test_domain.py")
    _write(tmp_path, f"{runtime_root}/install_bundle_tree/test_scaffold.py")
    _write(tmp_path, f"{runtime_root}/domain/machine_qa.py")

    assert (
        hc.scan_runtime_module_names(
            tmp_path,
            runtime_root=runtime_root,
        )
        == []
    )
