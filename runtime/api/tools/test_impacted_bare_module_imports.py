"""Pytest prepend imports add edges without replacing full module names."""

from pathlib import Path

import pytest

from yoke_core.tools._impacted_import_index import build_import_index, reachable_tests


def _write(root: Path, rel: str, body: str = "") -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


@pytest.fixture
def helper_tree(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(
        "yoke_core.tools._impacted_import_index.current_test_roots",
        lambda: ("checks/",),
    )
    for rel in (
        "checks/helpers.py",
        "checks/pkg/__init__.py",
        "checks/pkg/nested/__init__.py",
        "checks/pkg/nested/helper.py",
        "checks/other/helpers.py",
    ):
        _write(tmp_path, rel)
    for name, body in {
        "bare": "from helpers import configure\n",
        "import": "import helpers\n",
        "package": "from pkg.nested.helper import configure\n",
        "full": "from checks.helpers import configure\n",
        "transitive": "import test_bare\n",
        "unrelated": "import unrelated\n",
    }.items():
        _write(tmp_path, f"checks/test_{name}.py", body)
    return tmp_path


def test_bare_imports_reach_exact_importers_and_transitive_tests(helper_tree: Path):
    index = build_import_index(helper_tree)

    assert reachable_tests(["checks/helpers.py"], index) == {
        "checks/test_bare.py",
        "checks/test_import.py",
        "checks/test_full.py",
        "checks/test_transitive.py",
    }
    assert index.module_of["checks/helpers.py"] == "checks.helpers"


def test_nested_package_name_uses_indexed_init_files(helper_tree: Path):
    index = build_import_index(helper_tree)

    assert reachable_tests(["checks/pkg/nested/helper.py"], index) == {
        "checks/test_package.py"
    }
    assert reachable_tests(["checks/pkg/nested/__init__.py"], index) == set()


def test_duplicate_bare_names_conservatively_select_importers(helper_tree: Path):
    index = build_import_index(helper_tree)

    assert reachable_tests(["checks/other/helpers.py"], index) == {
        "checks/test_bare.py",
        "checks/test_import.py",
        "checks/test_transitive.py",
    }


def test_existing_full_module_edges_are_preserved(helper_tree: Path):
    index = build_import_index(helper_tree)
    # Remove only the added alias edges to reconstruct the previous graph.
    from dataclasses import replace

    previous = replace(index, importers={"checks.helpers": {"checks/test_full.py"}})
    before = reachable_tests(["checks/helpers.py"], previous)
    after = reachable_tests(["checks/helpers.py"], index)
    assert before == {"checks/test_full.py"}
    assert before <= after


def test_source_packages_and_project_checks_do_not_gain_bare_aliases(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        "yoke_core.tools._impacted_import_index.current_test_roots",
        lambda: ("checks/",),
    )
    _write(tmp_path, "packages/demo/src/demo/helper.py")
    _write(tmp_path, ".yoke/doctor/check_helper.py")
    _write(tmp_path, "checks/test_bare.py", "import helper\nimport check_helper\n")
    _write(
        tmp_path,
        "checks/test_named.py",
        "import demo.helper\nimport yoke_project_checks.check_helper\n",
    )
    index = build_import_index(tmp_path)
    for subject in (
        "packages/demo/src/demo/helper.py",
        ".yoke/doctor/check_helper.py",
    ):
        assert reachable_tests([subject], index) == {"checks/test_named.py"}


def test_public_installer_helper_selects_all_importers(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.tools._impacted_import_index.current_test_roots",
        lambda: ("tests/",),
    )
    root = Path(__file__).resolve().parents[3]
    index = build_import_index(root)
    expected = {
        path.relative_to(root).as_posix()
        for path in (root / "tests/installer").glob("test_public_installer_*.py")
        if "from public_installer_helpers import" in path.read_text(encoding="utf-8")
    }
    assert len(expected) == 16
    assert expected <= reachable_tests(
        ["tests/installer/public_installer_helpers.py"], index
    )
