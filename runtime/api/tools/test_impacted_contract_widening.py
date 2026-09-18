"""Regression coverage for contract-selected impacted tests and telemetry."""

from yoke_core.tools import impacted_tests
from yoke_core.tools import _impacted_contract_prefix_families as prefix_contracts
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


def test_cli_registry_change_selects_the_registry_usage_parity_tests(tmp_path):
    """A new CLI route couples to its usage entry by dict key, not import."""
    root = _tiny_repo(tmp_path)
    registry = "packages/yoke-cli/src/yoke_cli/commands/registry.py"
    manifest_test = "runtime/api/cli/test_yoke_cli_manifest.py"
    operations_test = "runtime/api/cli/test_yoke_operations_cli.py"
    journey_test = "runtime/api/cli/test_fleet_message_cli_user_journey.py"
    selector_help_test = "runtime/api/cli/test_session_control_selector_help.py"
    _write(root, registry, "SUBCOMMAND_REGISTRY = {}\n")
    _write(root, manifest_test, "def test_manifest_usage(): pass\n")
    _write(root, operations_test, "def test_usage_entry(): pass\n")
    _write(root, journey_test, "def test_fleet_journey(): pass\n")
    _write(root, selector_help_test, "def test_selector_help(): pass\n")

    selection = select([registry], build_import_index(root))

    assert selection.full_sweep is False
    assert manifest_test in selection.files
    assert operations_test in selection.files
    assert journey_test in selection.files
    assert selector_help_test in selection.files
    assert f"product_cli_boundary_contract:{registry}" in selection.telemetry()


def test_session_schema_change_selects_boot_column_convergence(tmp_path):
    root = _tiny_repo(tmp_path)
    source = "packages/yoke-core/src/yoke_core/domain/session_control_schema.py"
    boot_test = "runtime/api/domain/test_boot_schema_column_convergence.py"
    _write(root, source, "def create_session_control_tables(): pass\n")
    _write(root, boot_test, "def test_boot_columns(): pass\n")

    selection = select([source], build_import_index(root))

    assert boot_test in selection.files
    assert f"migration_history_contract:{source}" in selection.telemetry()


def test_universe_ui_javascript_selects_node_mount_contract(tmp_path):
    root = _tiny_repo(tmp_path)
    source = "packages/yoke-core/src/yoke_core/ui/static/universe_views_inbox.js"
    mount_test = prefix_contracts.UNIVERSE_UI_CONTRACT_TESTS[0]
    _write(root, source, "export const inbox = {};\n")
    _write(root, mount_test, "def test_node_modules(): pass\n")

    selection = select([source], build_import_index(root), bounded=True)

    assert selection.bounded_deferral is True
    assert mount_test in selection.files
    assert f"universe_ui_contract:{source}" in selection.telemetry()


def test_inbox_composition_selects_its_handler_boundary(tmp_path):
    root = _tiny_repo(tmp_path)
    source = "packages/yoke-core/src/yoke_core/domain/inbox_read.py"
    handler_test = prefix_contracts.INBOX_COMPOSITION_CONTRACT_TESTS[0]
    _write(root, source, "def inbox_for_actor(): pass\n")
    _write(root, handler_test, "def test_inbox_handler(): pass\n")

    selection = select([source], build_import_index(root))

    assert handler_test in selection.files
    assert f"inbox_composition_contract:{source}" in selection.telemetry()


def test_registering_a_handler_selects_the_authorization_classification(tmp_path):
    """A newly registered function id reaches its authz contract by registry."""
    root = _tiny_repo(tmp_path)
    registrar = "packages/yoke-core/src/yoke_core/domain/handlers/_register_widgets.py"
    authz_test = "runtime/api/domain/test_function_authz_scope_routing.py"
    _write(root, registrar, "def register(registry): pass\n")
    _write(root, authz_test, "def test_every_function_is_classified(): pass\n")

    selection = select([registrar], build_import_index(root))

    assert selection.full_sweep is False
    assert authz_test in selection.files
    assert f"handler_registration_contract:{registrar}" in selection.telemetry()


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


def test_a_harness_package_edit_selects_the_client_import_boundary(tmp_path):
    """The boundary tests police every client package, not just the CLI.

    They scan the source tree rather than importing what they check, so
    reachability can never link them to the file that breaks them, and they
    rode in a family triggered by the CLI's own source. An import added under
    yoke-harness therefore reached a green selection and a red suite -- the
    exact violation these two exist to catch.
    """
    root = _tiny_repo(tmp_path)
    harness_source = "packages/yoke-harness/src/yoke_harness/session_relay_cursor.py"
    skeleton_test = "tests/import_graph/test_skeletons_importable.py"
    installer_test = "runtime/api/test_installer_package_boundaries.py"
    _write(root, harness_source, "def resume(): pass\n")
    _write(root, skeleton_test, "def test_client_packages(): pass\n")
    _write(root, installer_test, "def test_direct_core_imports(): pass\n")

    selection = select([harness_source], build_import_index(root))

    assert selection.full_sweep is False
    assert skeleton_test in selection.files
    assert installer_test in selection.files
    assert (
        f"client_package_boundary_contract:{harness_source}" in selection.telemetry()
    )


def test_a_contracts_package_edit_selects_them_too(tmp_path):
    """yoke-contracts is a client package on the same terms."""
    root = _tiny_repo(tmp_path)
    contract_source = "packages/yoke-contracts/src/yoke_contracts/process_ancestry.py"
    skeleton_test = "tests/import_graph/test_skeletons_importable.py"
    _write(root, contract_source, "def process_start_time(): pass\n")
    _write(root, skeleton_test, "def test_client_packages(): pass\n")

    selection = select([contract_source], build_import_index(root))

    assert skeleton_test in selection.files


def test_every_client_package_root_is_named_by_the_boundary_trigger():
    """A new client package that is not listed here is silently unpoliced."""
    assert set(prefix_contracts.CLIENT_PACKAGE_SOURCE_PREFIXES) == {
        "packages/yoke-cli/src/yoke_cli/",
        "packages/yoke-contracts/src/yoke_contracts/",
        "packages/yoke-harness/src/yoke_harness/",
    }
