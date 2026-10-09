"""Policy prose keeps its verification contract in bounded selections."""

import pytest

from runtime.api.tools.test_impacted_tests_contract_mappings import _write
from yoke_core.tools import _impacted_contract_tests_path_claims as path_claims
from yoke_core.tools import impacted_tests
from yoke_core.tools.impacted_tests import build_import_index, select


@pytest.mark.parametrize("source", sorted(path_claims.OVERRIDE_POLICY_SOURCE_PATHS))
def test_override_policy_teaching_keeps_its_contract_in_bounded_selection(
    tmp_path, source
):
    _write(tmp_path, source, "Override requires covering authority\n")
    for path in {*impacted_tests.ALWAYS_RUN_TESTS, *path_claims.OVERRIDE_POLICY_TESTS}:
        _write(tmp_path, path, "def test_contract(): pass\n")
    selection = select([source], build_import_index(tmp_path), bounded=True)
    assert set(path_claims.OVERRIDE_POLICY_TESTS) <= set(selection.files)
