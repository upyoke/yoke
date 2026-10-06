"""Conftest and fixture-plugin changes select the tests that use them."""

from yoke_core.tools.impacted_tests import build_import_index, select
from runtime.api.tools.test_impacted_tests import _tiny_repo, _write

_FIXTURES = """import pytest
from runtime.api.marker_helpers import VALUE


@pytest.fixture
def marker():
    return VALUE


@pytest.fixture
def plain():
    return 1


@pytest.fixture
def wrapped(marker):
    return marker
"""


def _repo_with_fixtures(tmp_path, conftest_body=_FIXTURES):
    root = _tiny_repo(tmp_path)
    _write(root, "runtime/api/marker_paths.py", "VALUE = 1\n")
    _write(
        root,
        "runtime/api/marker_helpers.py",
        "from runtime.api.marker_paths import VALUE\n",
    )
    _write(root, "runtime/harness/conftest.py", conftest_body)
    _write(root, "runtime/harness/test_marker.py", "def test_it(marker): pass\n")
    _write(root, "runtime/harness/test_wrapped.py", "def test_it(wrapped): pass\n")
    _write(root, "runtime/harness/test_plain.py", "def test_it(plain): pass\n")
    _write(
        root,
        "runtime/harness/test_marked.py",
        "import pytest\n\npytestmark = pytest.mark.usefixtures('marker')\n",
    )
    _write(root, "runtime/harness/test_other.py", "def test_it(): pass\n")
    _write(root, "runtime/api/test_outside.py", "def test_it(marker): pass\n")
    return root


def test_changed_conftest_selects_tests_requesting_its_fixtures(tmp_path):
    root = _repo_with_fixtures(tmp_path)

    selection = select(["runtime/harness/conftest.py"], build_import_index(root))

    assert selection.full_sweep is False
    assert {
        "runtime/harness/test_marker.py",
        "runtime/harness/test_wrapped.py",
        "runtime/harness/test_plain.py",
        "runtime/harness/test_marked.py",
    } <= set(selection.files)
    # Out of the conftest's directory, the same parameter name is not its.
    assert "runtime/api/test_outside.py" not in selection.files


def test_reached_import_selects_only_fixtures_that_use_it(tmp_path):
    root = _repo_with_fixtures(tmp_path)

    selection = select(
        ["runtime/api/marker_paths.py"], build_import_index(root), bounded=True
    )

    assert {
        "runtime/harness/test_marker.py",
        "runtime/harness/test_wrapped.py",
        "runtime/harness/test_marked.py",
    } <= set(selection.files)
    assert "runtime/harness/test_plain.py" not in selection.files


def test_autouse_fixture_makes_every_test_in_scope_a_dependent(tmp_path):
    body = _FIXTURES.replace(
        "@pytest.fixture\ndef plain", "@pytest.fixture(autouse=True)\ndef plain"
    )
    root = _repo_with_fixtures(tmp_path, body)

    selection = select(["runtime/harness/conftest.py"], build_import_index(root))

    assert "runtime/harness/test_other.py" in selection.files
    assert "runtime/api/test_outside.py" not in selection.files


def test_descendant_conftest_carries_a_requested_fixture_into_its_scope(tmp_path):
    root = _repo_with_fixtures(tmp_path)
    _write(
        root,
        "runtime/harness/nested/conftest.py",
        "import pytest\n\n\n@pytest.fixture\ndef nested(marker):\n    return marker\n",
    )
    _write(root, "runtime/harness/nested/test_nested.py", "def test_it(nested): pass\n")

    selection = select(["runtime/harness/conftest.py"], build_import_index(root))

    assert "runtime/harness/nested/test_nested.py" in selection.files


def test_fixture_plugin_scopes_to_its_declaring_conftest(tmp_path):
    root = _tiny_repo(tmp_path)
    _write(root, "runtime/harness/__init__.py", "")
    _write(
        root,
        "runtime/harness/plugins.py",
        "import pytest\n\n\n@pytest.fixture\ndef seeded():\n    return 1\n",
    )
    _write(
        root,
        "runtime/harness/conftest.py",
        "pytest_plugins = ['runtime.harness.plugins']\n",
    )
    _write(root, "runtime/harness/test_seeded.py", "def test_it(seeded): pass\n")
    _write(root, "runtime/harness/test_other.py", "def test_it(): pass\n")

    selection = select(["runtime/harness/plugins.py"], build_import_index(root))

    assert "runtime/harness/test_seeded.py" in selection.files
    # A plugin scopes to its declaring conftest's directory.
    assert "runtime/api/test_middle.py" not in selection.files


def test_transitive_conftest_dependency_keeps_a_collection_probe(tmp_path):
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


def test_repository_root_conftest_hooks_reach_every_test(tmp_path):
    root = tmp_path
    _write(root, "conftest.py", "def pytest_configure(config):\n    pass\n")
    _write(root, "runtime/api/test_collection.py", "def test_it(): pass\n")
    _write(root, "runtime/harness/test_hooks.py", "def test_it(): pass\n")
    selection = select(["conftest.py"], build_import_index(root), bounded=True)
    assert {
        "runtime/api/test_collection.py",
        "runtime/harness/test_hooks.py",
    } <= set(selection.files)
