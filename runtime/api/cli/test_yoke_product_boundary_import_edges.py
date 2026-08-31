"""Dynamic authority edges in the product-boundary inventory."""

from yoke_cli import product_boundary_inventory as inventory

from runtime.api.cli.test_yoke_product_boundary_inventory import _rows


def test_hook_and_operator_boundaries_keep_their_own_dispositions():
    rows = _rows()
    hook = rows["yoke hook evaluate"]
    assert hook.disposition == inventory.HOOK_LOCAL_SUBSET
    assert hook.transport_branch == "hook-local-or-https-relay"
    assert {(edge.target, edge.classification) for edge in hook.import_edges} == {
        (
            "yoke_core.hooks.local_entry",
            "local_universe_dispatch",
        ),
        ("yoke_core.domain.session_orientation", "client_local_diagnostics"),
    }
    claim = rows[
        "python3 -m yoke_core.api.service_client coordination-claim-acquire"
    ]
    assert claim.disposition == inventory.OPERATOR_DEBUG_PERMANENT
    assert claim.transport_branch == "operator-debug-command"
    assert claim.owner == "claims.coordination_claim"
    raw_read = rows["python3 -m yoke_core.cli.db_router query"]
    assert raw_read.disposition == inventory.OPERATOR_DEBUG_PERMANENT
    assert raw_read.transport_branch == "operator-debug-command"
    assert raw_read.owner == "raw.sql"


def test_dynamic_import_classification_is_loaded_from_boundary_facts():
    rows = _rows()
    helper = rows["helper yoke_cli.project_install.source_dev"]
    assert helper.disposition == inventory.SOURCE_DEV_ADMIN
    assert (
        "yoke_core.domain.project_install_source_link",
        "source_dev_admin",
    ) in {(edge.target, edge.classification) for edge in helper.import_edges}
    prewarm = rows["yoke dev path-snapshot-prewarm"]
    assert {(edge.target, edge.classification) for edge in prewarm.import_edges} >= {
        ("yoke_core.domain.db_helpers", "source_dev_admin"),
        ("yoke_core.domain.path_snapshots", "source_dev_admin"),
        (
            "yoke_core.domain.path_snapshots_integration_warm",
            "source_dev_admin",
        ),
    }
    source_authority = rows["yoke source-authority quiesce"]
    assert (
        "yoke_core.domain.source_authority_cutover",
        "source_dev_admin",
    ) in {(edge.target, edge.classification) for edge in source_authority.import_edges}


def test_local_machine_edges_stay_on_the_client_helper_path():
    rows = _rows()
    dispatcher = rows["helper yoke_cli.transport.dispatcher"]
    lane_cleanup = rows["helper yoke_cli.commands._helpers"]
    handler_load = rows["helper yoke_cli.commands.local_dispatch_preload"]
    schema_converge = rows["helper yoke_cli.engine_upgrade_convergence"]
    for row in (dispatcher, lane_cleanup, handler_load, schema_converge):
        assert row.disposition == inventory.CLIENT_LOCAL_HELPER
    assert {edge.classification for edge in dispatcher.import_edges} == {
        "local_universe_dispatch"
    }
    assert {edge.classification for edge in lane_cleanup.import_edges} == {
        "client_local_machine_state",
    }
    assert {edge.classification for edge in handler_load.import_edges} == {
        "local_universe_dispatch",
    }
    assert {edge.classification for edge in schema_converge.import_edges} == {
        "local_universe_dispatch",
    }


def test_product_and_https_rows_do_not_hide_authority_import_edges():
    forbidden_classes = {
        "local_universe_dispatch",
        "project_layer_writer",
        "source_dev_admin",
        "static_authority_import",
        "unclassified_dynamic_authority_import",
    }
    for row in _rows().values():
        if row.disposition not in {
            inventory.PRODUCT_CLIENT,
            inventory.HTTPS_RELAY,
        }:
            continue
        assert (
            not {edge.classification for edge in row.import_edges} & forbidden_classes
        ), row
