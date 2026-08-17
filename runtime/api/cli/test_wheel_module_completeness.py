"""Clean-build source-to-wheel runtime completeness contract."""

from __future__ import annotations

import importlib.util
import sys
import types
import zipfile
from pathlib import Path

import pytest

from yoke_core.tools import product_wheel_validation, wheel_module_completeness


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_runtime_module_prefix_is_not_mistaken_for_test_support(tmp_path: Path) -> None:
    package_root = _source_tree(tmp_path)
    wheel = _wheel(
        tmp_path,
        {
            "yoke_core/__init__.py",
            "yoke_core/domain/__init__.py",
            "yoke_core/domain/test_named_runtime.py",
        },
    )

    report = wheel_module_completeness.assert_wheel_module_completeness(
        package_root, wheel
    )

    assert "yoke_core/domain/test_named_runtime.py" in report.wheel_members


def test_missing_source_runtime_module_fails_artifact_gate(tmp_path: Path) -> None:
    package_root = _source_tree(tmp_path)
    wheel = _wheel(
        tmp_path,
        {
            "yoke_core/__init__.py",
            "yoke_core/domain/__init__.py",
        },
    )

    with pytest.raises(
        wheel_module_completeness.WheelModuleCompletenessError,
        match="test_named_runtime.py",
    ):
        wheel_module_completeness.assert_wheel_module_completeness(package_root, wheel)


def test_stale_staging_module_fails_artifact_gate(tmp_path: Path) -> None:
    package_root = _source_tree(tmp_path)
    wheel = _wheel(
        tmp_path,
        {
            "yoke_core/__init__.py",
            "yoke_core/domain/__init__.py",
            "yoke_core/domain/test_named_runtime.py",
            "yoke_core/domain/deleted_runtime.py",
        },
    )

    with pytest.raises(
        wheel_module_completeness.WheelModuleCompletenessError,
        match="unexpected runtime modules.*deleted_runtime.py",
    ):
        wheel_module_completeness.assert_wheel_module_completeness(package_root, wheel)


def test_build_command_clears_incremental_module_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging_was_clean: list[bool] = []

    class FakeBuildPy:
        def run(self) -> None:
            staging_was_clean.append(not Path(self.build_lib).exists())

        def find_package_modules(self, _package, _package_dir):
            return []

    setuptools = types.ModuleType("setuptools")
    setuptools.setup = lambda **_kwargs: None
    command = types.ModuleType("setuptools.command")
    build_module = types.ModuleType("setuptools.command.build_py")
    build_module.build_py = FakeBuildPy
    monkeypatch.setitem(sys.modules, "setuptools", setuptools)
    monkeypatch.setitem(sys.modules, "setuptools.command", command)
    monkeypatch.setitem(sys.modules, "setuptools.command.build_py", build_module)
    spec = importlib.util.spec_from_file_location(
        "yoke_core_product_setup",
        REPO_ROOT / "packages/yoke-core/setup.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    build_lib = tmp_path / "build/lib"
    stale = build_lib / "yoke_core/domain/deleted_runtime.py"
    stale.parent.mkdir(parents=True)
    stale.write_text("STALE = True\n", encoding="utf-8")
    build_command = module.ProductBuildPy()
    build_command.build_lib = str(build_lib)

    build_command.run()

    assert staging_was_clean == [True]


def test_factory_boot_uses_only_the_built_wheelhouse(tmp_path: Path) -> None:
    commands: list[tuple[list[str], Path]] = []
    created: list[Path] = []

    product_wheel_validation.verify_product_wheel_boot(
        tmp_path / "wheelhouse",
        create_venv=created.append,
        run=lambda command, *, cwd: commands.append((list(command), cwd)),
    )

    assert len(created) == 1
    assert commands[0][0][-1] == "yoke-core"
    assert "--no-index" in commands[0][0]
    assert commands[1][0][-2:] == [
        "-m",
        "yoke_core.tools.product_wheel_validation",
    ]
    assert commands[0][1] == commands[1][1] == created[0]


def _source_tree(root: Path) -> Path:
    package_root = root / "src" / "yoke_core"
    domain = package_root / "domain"
    domain.mkdir(parents=True)
    for path in (
        package_root / "__init__.py",
        domain / "__init__.py",
        domain / "test_named_runtime.py",
        domain / "fixture_test_support.py",
    ):
        path.write_text("", encoding="utf-8")
    return package_root


def _wheel(root: Path, members: set[str]) -> Path:
    wheel = root / "yoke_core-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for member in members:
            archive.writestr(member, "")
    return wheel
