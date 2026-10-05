"""Implicit pytest collection imports survive bounded reachability deferral."""

from yoke_core.tools.impacted_tests import build_import_index, select
from runtime.api.tools.test_impacted_tests import _tiny_repo, _write


def test_transitive_conftest_dependency_selects_collection_probe(tmp_path):
    root = _tiny_repo(tmp_path)
    source = "runtime/api/marker_paths.py"
    _write(root, source, "VALUE = 1\n")
    _write(
        root,
        "runtime/api/marker_helpers.py",
        "from runtime.api.marker_paths import VALUE\n",
    )
    _write(
        root,
        "runtime/harness/conftest.py",
        "from runtime.api.marker_helpers import VALUE\n",
    )
    _write(root, "runtime/harness/test_hooks.py", "def test_it(): pass\n")
    _write(root, "runtime/harness/test_other.py", "def test_it(): pass\n")
    selection = select([source], build_import_index(root), bounded=True)
    assert "runtime/harness/test_hooks.py" in selection.files
    assert "runtime/harness/test_other.py" not in selection.files


def test_changed_conftest_retains_probe_when_full_coverage_is_deferred(tmp_path):
    root = _tiny_repo(tmp_path)
    owner = "runtime/harness/conftest.py"
    _write(root, owner, "")
    _write(root, "runtime/harness/test_hooks.py", "def test_it(): pass\n")
    selection = select([owner], build_import_index(root), bounded=True)
    assert selection.bounded_deferral
    assert "runtime/harness/test_hooks.py" in selection.files


def test_repository_root_conftest_selects_a_descendant_probe(tmp_path):
    root = _tiny_repo(tmp_path)
    _write(root, "conftest.py", "")
    _write(root, "runtime/api/test_collection.py", "def test_it(): pass\n")
    selection = select(["conftest.py"], build_import_index(root), bounded=True)
    assert "runtime/api/test_collection.py" in selection.files
