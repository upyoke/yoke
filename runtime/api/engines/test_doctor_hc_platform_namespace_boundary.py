"""Tests for HC-platform-namespace-boundary."""

from __future__ import annotations

from pathlib import Path

from yoke_core.api.repo_root import find_repo_root
from yoke_core.engines import doctor_hc_platform_namespace_boundary as hc
from yoke_core.engines.doctor_registry_architecture import (
    ARCHITECTURE_HEALTH_CHECKS,
)

NS = hc.PRIVATE_PLATFORM_NAMESPACE


def _write(root: Path, relpath: str, text: str) -> Path:
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def test_real_tree_has_no_platform_namespace_reference() -> None:
    repo_root = find_repo_root(Path(hc.__file__))
    assert hc.scan_platform_namespace_boundary(repo_root) == []


def test_import_shapes_fail(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/yoke-core/src/yoke_core/domain/plain.py",
        f"import {NS}\n",
    )
    _write(
        tmp_path,
        "packages/yoke-core/src/yoke_core/domain/dotted.py",
        f"import {NS}.control as control\n",
    )
    _write(
        tmp_path,
        "runtime/api/engines/from_root.py",
        f"from {NS} import control\n",
    )
    _write(
        tmp_path,
        "runtime/api/engines/from_dotted.py",
        f"from {NS}.control import dispatch\n",
    )

    findings = hc.scan_python_imports(tmp_path)

    assert {(f.relpath, f.line_no) for f in findings} == {
        ("packages/yoke-core/src/yoke_core/domain/plain.py", 1),
        ("packages/yoke-core/src/yoke_core/domain/dotted.py", 1),
        ("runtime/api/engines/from_root.py", 1),
        ("runtime/api/engines/from_dotted.py", 1),
    }


def test_top_level_python_file_is_scanned(tmp_path: Path) -> None:
    _write(tmp_path, "conftest.py", f"import {NS}\n")

    findings = hc.scan_python_imports(tmp_path)

    assert [(f.relpath, f.line_no) for f in findings] == [("conftest.py", 1)]


def test_similar_names_strings_and_comments_pass(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/yoke-core/src/yoke_core/domain/adjacent.py",
        f"import {NS}_adjacent\n"
        f"from product import {NS}\n"
        f'MENTION = "import {NS}"\n'
        f"# import {NS}\n",
    )

    assert hc.scan_python_imports(tmp_path) == []


def test_unparseable_source_falls_back_to_line_scan(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packs/example/versions/1.0.0/files/service.py",
        "def {{handler_name}}():\n"
        f"    import {NS}\n"
        f"    import {NS}_adjacent\n",
    )

    findings = hc.scan_python_imports(tmp_path)

    assert [(f.relpath, f.line_no) for f in findings] == [
        ("packs/example/versions/1.0.0/files/service.py", 2),
    ]


def test_pyproject_dependency_shapes_fail(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        "[build-system]\n"
        f'requires = ["setuptools", "{NS}_build"]\n'
        "\n"
        "[project]\n"
        'name = "product"\n'
        f'dependencies = ["{NS}>=1.0"]\n'
        "\n"
        "[project.optional-dependencies]\n"
        f'dev = ["{NS}-platform[extra]==2.0"]\n'
        "\n"
        "[dependency-groups]\n"
        f'test = ["{NS}"]\n',
    )

    findings = hc.scan_pyproject_dependencies(tmp_path)

    assert {(f.relpath, f.detail) for f in findings} == {
        ("pyproject.toml", f'dependency "{NS}>=1.0"'),
        ("pyproject.toml", f'dependency "{NS}-platform[extra]==2.0"'),
        ("pyproject.toml", f'dependency "{NS}_build"'),
        ("pyproject.toml", f'dependency "{NS}"'),
    }
    assert all(f.line_no > 0 for f in findings)


def test_pyproject_mixed_case_dependency_fails(tmp_path: Path) -> None:
    # PEP 503: requirement names are case-insensitive, so a re-cased
    # platform distribution must not slip past the scan.
    mixed = "".join(
        ch.upper() if i % 2 == 0 else ch for i, ch in enumerate(NS)
    )
    assert mixed != NS
    _write(
        tmp_path,
        "pyproject.toml",
        "[project]\n"
        'name = "product"\n'
        f'dependencies = ["{mixed}>=1.0"]\n',
    )

    findings = hc.scan_pyproject_dependencies(tmp_path)

    assert [(f.relpath, f.detail) for f in findings] == [
        ("pyproject.toml", f'dependency "{mixed}>=1.0"'),
    ]


def test_nested_package_pyproject_is_scanned(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "packages/yoke-core/pyproject.toml",
        "[project]\n"
        'name = "yoke-core"\n'
        f'dependencies = ["{NS}"]\n',
    )

    findings = hc.scan_pyproject_dependencies(tmp_path)

    assert [f.relpath for f in findings] == ["packages/yoke-core/pyproject.toml"]


def test_pyproject_unrelated_names_pass(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        "[project]\n"
        'name = "product"\n'
        f'# docs live at api.{NS}.com\n'
        f'dependencies = ["yoke-core", "not{NS}", "requests"]\n',
    )

    assert hc.scan_pyproject_dependencies(tmp_path) == []


def test_registered_in_architecture_bundle() -> None:
    matches = [
        check
        for check in ARCHITECTURE_HEALTH_CHECKS
        if check.slug == "platform-namespace-boundary"
    ]
    assert len(matches) == 1
    assert matches[0].fn is hc.hc_platform_namespace_boundary
    assert matches[0].name == hc.HC_DESC
