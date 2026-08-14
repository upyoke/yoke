"""Tests for import-reachability test selection."""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import impacted_tests
from yoke_core.tools._impacted_contract_tests import (
    WORKFLOW_DEFINITION_VALIDATION_TESTS,
)
from yoke_core.tools.impacted_tests import (
    ImportIndex,
    Selection,
    build_import_index,
    is_test_file,
    module_name_for,
    select,
)


def test_module_name_for_package_and_repo_layouts():
    assert (
        module_name_for("packages/yoke-core/src/yoke_core/domain/db_backend.py")
        == "yoke_core.domain.db_backend"
    )
    assert (
        module_name_for("packages/yoke-core/src/yoke_core/domain/__init__.py")
        == "yoke_core.domain"
    )
    assert (
        module_name_for("runtime/api/fixtures/pg_testdb.py")
        == "runtime.api.fixtures.pg_testdb"
    )
    assert module_name_for("docs/testing-verification.md") is None


def test_is_test_file():
    assert is_test_file("runtime/api/test_thing.py") is True
    assert is_test_file("runtime/harness/test_adapter.py") is True
    assert is_test_file("tests/import_graph/test_contract.py") is True
    assert is_test_file("runtime/api/thing_test.py") is False
    assert is_test_file("runtime/api/testing_helper.py") is False
    assert (
        is_test_file("packages/yoke-core/src/yoke_core/domain/handlers/test_machine.py")
        is False
    )


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _with_floor(*tests: str) -> tuple[str, ...]:
    """Expected selection: the reached tests plus the always-run floor."""
    return tuple(sorted({*tests, *impacted_tests.ALWAYS_RUN_TESTS}))


def _tiny_repo(tmp_path: Path) -> Path:
    _write(tmp_path, "runtime/__init__.py", "")
    _write(tmp_path, "runtime/api/__init__.py", "")
    _write(tmp_path, "runtime/api/leaf.py", "VALUE = 1\n")
    _write(tmp_path, "runtime/api/middle.py", "from runtime.api import leaf\n")
    _write(tmp_path, "runtime/api/unrelated.py", "OTHER = 2\n")
    _write(
        tmp_path,
        "runtime/api/test_middle.py",
        "from runtime.api import middle\n\ndef test_x():\n    pass\n",
    )
    _write(
        tmp_path,
        "runtime/api/test_unrelated.py",
        "from runtime.api import unrelated\n\ndef test_y():\n    pass\n",
    )
    return tmp_path


def test_selects_transitively_reachable_tests_only(tmp_path):
    root = _tiny_repo(tmp_path)
    index = build_import_index(root)

    selection = select(["runtime/api/leaf.py"], index)

    assert selection.full_sweep is False
    # test_middle imports middle, which imports leaf — two hops.
    assert selection.files == _with_floor("runtime/api/test_middle.py")


def test_changed_test_file_selects_itself(tmp_path):
    root = _tiny_repo(tmp_path)
    index = build_import_index(root)

    selection = select(["runtime/api/test_unrelated.py"], index)

    assert selection.files == _with_floor("runtime/api/test_unrelated.py")


def test_deleted_test_file_is_not_a_runnable_pytest_path(tmp_path):
    root = _tiny_repo(tmp_path)
    index = build_import_index(root)

    selection = select(["runtime/api/leaf.py", "runtime/api/test_deleted.py"], index)

    assert "runtime/api/test_deleted.py" not in selection.files
    assert selection.files == _with_floor("runtime/api/test_middle.py")


def test_non_python_change_forces_full_sweep(tmp_path):
    index = build_import_index(_tiny_repo(tmp_path))

    selection = select(["docs/lifecycle.md"], index)

    assert selection.full_sweep is True
    assert "not a Python module" in selection.reason
    assert selection.pytest_paths() == impacted_tests.TEST_ANCHORS


def test_shared_fixture_change_forces_full_sweep(tmp_path):
    index = build_import_index(_tiny_repo(tmp_path))

    selection = select(["runtime/api/fixtures/pg_testdb.py"], index)

    assert selection.full_sweep is True
    assert "any test" in selection.reason


def test_conftest_change_forces_full_sweep(tmp_path):
    index = build_import_index(_tiny_repo(tmp_path))

    selection = select(["runtime/api/conftest.py"], index)

    assert selection.full_sweep is True


def test_test_tooling_change_forces_full_sweep(tmp_path):
    index = build_import_index(_tiny_repo(tmp_path))

    selection = select(
        ["packages/yoke-core/src/yoke_core/tools/gate_admission.py"], index
    )

    assert selection.full_sweep is True


def test_unimportable_module_change_forces_full_sweep(tmp_path):
    index = build_import_index(_tiny_repo(tmp_path))

    # A .py path the index never saw: treat it as unbounded rather than
    # silently selecting nothing.
    selection = select(["scripts/one_off.py"], index)

    assert selection.full_sweep is True
    assert "no importable module" in selection.reason


def test_relative_imports_are_resolved(tmp_path):
    _write(tmp_path, "runtime/__init__.py", "")
    _write(tmp_path, "runtime/api/__init__.py", "")
    _write(tmp_path, "runtime/api/pkg/__init__.py", "")
    _write(tmp_path, "runtime/api/pkg/core.py", "X = 1\n")
    _write(
        tmp_path,
        "runtime/api/pkg/test_core_relative.py",
        "from . import core\n\ndef test_z():\n    pass\n",
    )
    index = build_import_index(tmp_path)

    selection = select(["runtime/api/pkg/core.py"], index)

    assert selection.files == _with_floor("runtime/api/pkg/test_core_relative.py")


def test_selection_pytest_paths_prefers_selected_tests():
    selected = Selection(full_sweep=False, reason="x", files=("a/test_b.py",))
    assert selected.pytest_paths() == ("a/test_b.py",)

    sweep = Selection(full_sweep=True, reason="y")
    assert sweep.pytest_paths() == impacted_tests.TEST_ANCHORS


def test_no_changes_selects_nothing():
    selection = select([], ImportIndex(importers={}, module_of={}))
    assert selection.full_sweep is False
    assert selection.files == ()


def test_subprocess_module_string_selects_the_shelling_test(tmp_path):
    root = _tiny_repo(tmp_path)
    _write(
        root,
        "runtime/api/test_leaf_cli.py",
        "import subprocess\n\n\ndef test_cli():\n"
        '    subprocess.run(["python3", "-m", "runtime.api.leaf"])\n',
    )
    index = build_import_index(root)

    selection = select(["runtime/api/leaf.py"], index)

    assert "runtime/api/test_leaf_cli.py" in selection.files


def test_patch_target_string_selects_the_patching_test(tmp_path):
    root = _tiny_repo(tmp_path)
    # The string names an attribute inside the module; the module prefix
    # of the dotted path is what must create the edge.
    _write(
        root,
        "runtime/api/test_leaf_patch.py",
        'TARGET = "runtime.api.leaf.VALUE"\n\n\ndef test_patched():\n    pass\n',
    )
    index = build_import_index(root)

    selection = select(["runtime/api/leaf.py"], index)

    assert "runtime/api/test_leaf_patch.py" in selection.files


def test_unreached_change_still_runs_the_contract_floor(tmp_path):
    root = _tiny_repo(tmp_path)
    _write(root, "runtime/api/orphan.py", "ALONE = 1\n")
    index = build_import_index(root)

    selection = select(["runtime/api/orphan.py"], index)

    assert selection.full_sweep is False
    assert "always-run" in selection.reason
    assert selection.files == _with_floor()


def test_repo_cleanliness_contract_is_always_selected(tmp_path):
    selection = select(["runtime/api/leaf.py"], build_import_index(_tiny_repo(tmp_path)))

    assert set(impacted_tests.REPO_CLEANLINESS_TESTS) <= set(selection.files)


def test_item_worktree_schema_change_runs_fixture_consumers(tmp_path):
    root = _tiny_repo(tmp_path)
    changed = "packages/yoke-core/src/yoke_core/domain/item_worktree_schema.py"
    tooling = "packages/yoke-core/src/yoke_core/tools/impacted_tests.py"
    _write(root, changed, "ITEM_WORKTREES_TABLE_SQL = ''\n")
    _write(root, tooling, "VALUE = 1\n")
    for test_path in impacted_tests.ITEM_WORKTREE_SCHEMA_TESTS:
        _write(root, test_path, "def test_fixture_contract(): pass\n")

    selection = select([changed, tooling], build_import_index(root), bounded=True)

    assert selection.bounded_deferral is True
    assert set(impacted_tests.ITEM_WORKTREE_SCHEMA_TESTS) <= set(selection.files)


def test_workflow_validation_change_keeps_bounded_contracts(tmp_path):
    root = _tiny_repo(tmp_path)
    changed = (
        "packages/yoke-core/src/yoke_core/domain/"
        "workflow_definition_validation.py"
    )
    tooling = (
        "packages/yoke-core/src/yoke_core/tools/"
        "_impacted_contract_tests.py"
    )
    _write(root, changed, "VALUE = 1\n")
    _write(root, tooling, "VALUE = 1\n")
    for test_path in WORKFLOW_DEFINITION_VALIDATION_TESTS:
        _write(root, test_path, "def test_validation_contract(): pass\n")

    selection = select([changed, tooling], build_import_index(root), bounded=True)

    assert selection.bounded_deferral is True
    assert set(WORKFLOW_DEFINITION_VALIDATION_TESTS) <= set(selection.files)


def test_schema_converge_change_keeps_cli_contract_when_selection_is_deferred(
    tmp_path,
):
    root = _tiny_repo(tmp_path)
    changed = "packages/yoke-cli/src/yoke_cli/commands/schema_converge.py"
    tooling = "packages/yoke-core/src/yoke_core/tools/impacted_tests.py"
    _write(root, changed, "def schema_converge(): pass\n")
    _write(root, tooling, "VALUE = 1\n")
    for test_path in impacted_tests.SCHEMA_CONVERGE_CONTRACT_TESTS:
        _write(root, test_path, "def test_schema_converge(): pass\n")

    selection = select([changed, tooling], build_import_index(root), bounded=True)

    assert selection.bounded_deferral is True
    assert set(impacted_tests.SCHEMA_CONVERGE_CONTRACT_TESTS) <= set(selection.files)


def test_product_cli_change_keeps_boundary_contracts_when_selection_is_deferred(
    tmp_path,
):
    root = _tiny_repo(tmp_path)
    changed = "packages/yoke-cli/src/yoke_cli/commands/merge_item.py"
    tooling = "packages/yoke-core/src/yoke_core/tools/impacted_tests.py"
    _write(root, changed, "def merge_item(): pass\n")
    _write(root, tooling, "VALUE = 1\n")
    for test_path in impacted_tests.PRODUCT_CLI_BOUNDARY_TESTS:
        _write(root, test_path, "def test_product_boundary(): pass\n")

    selection = select([changed, tooling], build_import_index(root), bounded=True)

    assert selection.bounded_deferral is True
    assert set(impacted_tests.PRODUCT_CLI_BOUNDARY_TESTS) <= set(selection.files)


def test_index_covers_a_root_nested_under_a_skipped_directory_name(tmp_path):
    """A linked worktree lives under ``.worktrees/``, which is skip-listed.

    Matching the skip list against absolute path parts makes every file
    inside such a root look skipped, leaving an empty index — which reads
    downstream as "nothing is importable" and widens every run to a full
    sweep, in exactly the checkouts where selection is worth the most.
    """
    root = tmp_path / ".worktrees" / "some-branch"
    root.mkdir(parents=True)
    _tiny_repo(root)

    index = build_import_index(root)
    selection = select(["runtime/api/leaf.py"], index)

    assert selection.full_sweep is False
    assert "runtime/api/test_middle.py" in selection.files


def test_skipped_directories_nested_inside_the_root_stay_skipped(tmp_path):
    root = _tiny_repo(tmp_path)
    _write(root, ".venv/lib/vendored.py", "from runtime.api import leaf\n")

    index = build_import_index(root)

    assert ".venv/lib/vendored.py" not in index.module_of


def test_always_run_tests_exist_in_this_repo():
    repo_root = Path(__file__).resolve().parents[3]
    required = (
        *impacted_tests.ALWAYS_RUN_TESTS,
        *impacted_tests.ITEM_WORKTREE_SCHEMA_TESTS,
        *impacted_tests.PRODUCT_CLI_BOUNDARY_TESTS,
        *impacted_tests.SCHEMA_CONVERGE_CONTRACT_TESTS,
        *WORKFLOW_DEFINITION_VALIDATION_TESTS,
    )
    for rel in required:
        assert (repo_root / rel).is_file(), rel
