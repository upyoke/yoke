"""Regression coverage for contract-selected impacted tests and telemetry."""

from yoke_core.tools import impacted_tests
from yoke_core.tools._impacted_contract_tests import (
    CURSOR_SESSION_IDENTITY_DISPATCH_TESTS,
)
from yoke_core.tools.impacted_tests import build_import_index, select

from runtime.api.tools.test_impacted_tests import _tiny_repo, _write


def test_cli_and_done_transition_contracts_name_their_widening_paths(tmp_path):
    root = _tiny_repo(tmp_path)
    cli_helper = "packages/yoke-cli/src/yoke_cli/commands/_helpers.py"
    done_runner = "packages/yoke-core/src/yoke_core/engines/done_transition_runner.py"
    cleanup_test = "runtime/api/engines/test_done_transition_cleanup_metadata.py"
    boundary_test = "runtime/api/cli/test_yoke_product_boundary_inventory.py"
    _write(root, cli_helper, "def dispatch_and_emit(): pass\n")
    _write(root, done_runner, "def run(): pass\n")
    _write(root, cleanup_test, "def test_cleanup_metadata(): pass\n")
    _write(root, boundary_test, "def test_boundary_inventory(): pass\n")

    selection = select([cli_helper, done_runner], build_import_index(root))

    assert selection.full_sweep is False
    assert cleanup_test in selection.files
    assert boundary_test in selection.files
    telemetry = selection.telemetry()
    assert f"done_transition_close_out_contract:{done_runner}" in telemetry
    assert f"product_cli_boundary_contract:{cli_helper}" in telemetry


def test_repo_cleanliness_floor_names_its_global_widening_trigger(tmp_path):
    root = _tiny_repo(tmp_path)
    payload = "packages/yoke-cli/src/yoke_cli/transport/control_plane_payload.py"
    payload_test = "runtime/api/domain/test_control_plane_payload_compatibility.py"
    cleanliness_test = impacted_tests.REPO_CLEANLINESS_TESTS[0]
    _write(root, payload, "PAYLOAD_VERSION = 1\n")
    _write(root, payload_test, "def test_payload_compatibility(): pass\n")
    _write(root, cleanliness_test, "def test_real_tree_is_clean(): pass\n")

    selection = select([payload, payload_test], build_import_index(root))

    assert selection.full_sweep is False
    assert cleanliness_test in selection.files
    assert "repo_cleanliness_contract:*" in selection.telemetry()


def test_cursor_identity_dispatch_survives_bounded_tooling_deferral(tmp_path):
    root = _tiny_repo(tmp_path)
    cursor_payload = "packages/yoke-core/src/yoke_core/hooks/cursor_payload.py"
    tooling = "packages/yoke-core/src/yoke_core/tools/_impacted_contract_tests.py"
    dispatch_test = CURSOR_SESSION_IDENTITY_DISPATCH_TESTS[0]
    _write(root, cursor_payload, "def resolve_container_session_id(): pass\n")
    _write(root, tooling, "VALUE = 1\n")
    _write(root, dispatch_test, "def test_session_dispatch(): pass\n")

    selection = select(
        [cursor_payload, tooling],
        build_import_index(root),
        bounded=True,
    )

    assert selection.bounded_deferral is True
    assert dispatch_test in selection.files
    assert (
        f"cursor_session_identity_dispatch_contract:{cursor_payload}"
        in selection.telemetry()
    )
