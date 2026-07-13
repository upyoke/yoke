from __future__ import annotations

from pathlib import Path

from yoke_cli import product_boundary_inventory as inventory
from yoke_cli import product_boundary_teaching as teaching


REPO_ROOT = Path(__file__).resolve().parents[3]


def _rows() -> dict[str, inventory.InventoryRow]:
    return {
        row.command_helper: row
        for row in inventory.generate_inventory(repo_root=REPO_ROOT)
    }


def test_representative_product_client_rows_are_separate_from_source_dev():
    rows = _rows()
    assert rows["yoke status"].disposition == inventory.PRODUCT_CLIENT
    assert rows["yoke status"].transport_branch == "product-client-local"
    assert rows["yoke onboard"].disposition == inventory.PRODUCT_CLIENT
    assert rows["yoke project install"].disposition == inventory.PRODUCT_CLIENT
    assert (
        rows["yoke project install"].transport_branch
        == "project-install-https-bundle"
    )
    assert rows["yoke github connect"].disposition == inventory.PRODUCT_CLIENT
    assert rows["yoke connect"].disposition == inventory.PRODUCT_CLIENT
    assert rows["yoke self-host init"].disposition == inventory.PRODUCT_CLIENT
    for command in ("yoke aws exec", "yoke dev setup",
                    "yoke dev db-admin setup",
                    "yoke dev path-snapshot-prewarm"):
        assert rows[command].disposition == inventory.SOURCE_DEV_ADMIN
    assert rows["yoke dev setup"].transport_branch == "source-dev-admin-local"

def test_hook_and_operator_boundaries_keep_their_own_dispositions():
    rows = _rows()
    hook = rows["yoke hook evaluate"]
    assert hook.disposition == inventory.HOOK_LOCAL_SUBSET
    assert hook.transport_branch == "hook-local-or-https-relay"
    assert {(edge.target, edge.classification) for edge in hook.import_edges} == {
        ("runtime.harness.hook_runner.local_universe_lifecycle",
         "local_universe_dispatch"),
    }

    lease = rows[
        "python3 -m yoke_core.api.service_client coordination-lease-acquire"
    ]
    assert lease.disposition == inventory.OPERATOR_DEBUG_PERMANENT
    assert lease.transport_branch == "operator-debug-command"
    assert lease.owner == "claims.coordination_lease"

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
    ) in {
        (edge.target, edge.classification)
        for edge in helper.import_edges
    }
    prewarm = rows["yoke dev path-snapshot-prewarm"]
    assert {
        (edge.target, edge.classification)
        for edge in prewarm.import_edges
    } >= {
        ("yoke_core.domain.db_helpers", "source_dev_admin"),
        ("yoke_core.domain.path_snapshots", "source_dev_admin"),
        (
            "yoke_core.domain.path_snapshots_integration_warm",
            "source_dev_admin",
        ),
    }


def test_local_universe_dispatch_edges_stay_product_path():
    rows = _rows()
    dispatcher = rows["helper yoke_cli.transport.dispatcher"]
    handler_load = rows["helper yoke_cli.commands._helpers"]
    for row in (dispatcher, handler_load):
        assert row.disposition == inventory.CLIENT_LOCAL_HELPER
        assert {edge.classification for edge in row.import_edges} == {
            "local_universe_dispatch"
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
        assert not {
            edge.classification
            for edge in row.import_edges
        } & forbidden_classes, row


def test_registry_operation_and_tool_shaped_surfaces_are_present():
    rows = _rows()
    assert rows["yoke items get"].function_id == "items.get.run"
    assert rows["yoke check file-line"].disposition == (
        inventory.CLIENT_LOCAL_HELPER
    )
    assert rows["yoke git pre-commit"].disposition == inventory.HOOK_LOCAL_SUBSET
    assert rows["yoke git pre-commit"].import_edges == ()
    assert rows["yoke git post-commit"].disposition == inventory.HOOK_LOCAL_SUBSET
    assert rows["yoke git post-commit"].import_edges == ()
    assert rows["yoke qa browser run"].disposition == inventory.CLIENT_LOCAL_HELPER
    assert rows["yoke qa browser run"].import_edges == ()
    assert rows["yoke qa browser screenshot"].disposition == (
        inventory.CLIENT_LOCAL_HELPER
    )
    assert rows["yoke qa browser screenshot"].import_edges == ()
    assert rows["yoke claims work current"].function_id == "claims.work.holder_get"
    assert rows["yoke deployment-runs get"].function_id == "deployment_runs.get"
    assert rows["yoke deployment-runs get"].disposition == inventory.HTTPS_RELAY
    assert rows["yoke ephemeral-env update"].function_id == "ephemeral_env.update"
    assert rows["yoke ephemeral-env update"].disposition == inventory.HTTPS_RELAY
    assert rows["yoke db read"].function_id == "db.read.run"
    assert rows["yoke db read"].disposition == inventory.HTTPS_RELAY
    assert rows[
        "python3 -m yoke_core.cli.db_router query"
    ].disposition == inventory.OPERATOR_DEBUG_PERMANENT
    assert rows[
        "yoke project-structure command-definitions get"
    ].disposition == inventory.HTTPS_RELAY
    assert rows[
        "yoke project-structure command-definitions list"
    ].function_id == "project_structure.command_definitions.list"
    assert rows["yoke qa run get"].function_id == "qa.run.get"
    assert rows["yoke qa run get"].disposition == inventory.HTTPS_RELAY
    assert rows["yoke readiness check"].function_id == "readiness.check.run"
    assert rows["yoke readiness check"].disposition == inventory.HTTPS_RELAY
    assert rows["yoke claims path required-gate"].function_id == (
        "claims.path.required_gate"
    )
    assert rows["yoke claims path activation-run"].function_id == (
        "claims.path.activation_run"
    )
    assert "python3 -m yoke_core.cli.db_router runs get" not in rows


def test_structured_adapter_inventory_tracks_db_read():
    from yoke_core.api.service_client_structured_api_adapter_inventory import (
        adapter_index,
    )
    entry = adapter_index()["db.read.run"]
    assert entry.cli_invocation == 'yoke db read "SELECT ..."'
    assert entry.read_shape is True


def test_markdown_renderer_is_deterministic_and_grouped():
    rows = tuple(inventory.generate_inventory(repo_root=REPO_ROOT))
    first = inventory.render_markdown(rows)
    second = inventory.render_markdown(rows)

    assert first == second
    assert first.startswith("# Yoke CLI Product-Boundary Inventory\n")
    assert "## product-client\n" in first
    assert "## source-dev/admin\n" in first
    assert first.index("## product-client") < first.index("## source-dev/admin")
    assert "| yoke status | status.run | product-client-local |" in first
    assert "TODO" not in first


def test_teaching_audit_accepts_tool_shaped_permanent_commands(tmp_path: Path):
    _write_doc(tmp_path, "```bash\nyoke board art variant create --ascii\n```\n")
    audit = inventory.generate_teaching_audit(repo_root=tmp_path)
    surface = _only_surface(audit)
    assert surface.command_form == "yoke board art variant create"
    assert surface.resolution == "tool_shaped"
    assert surface.status == "permanent"
    assert surface.reason == "tool_shaped"
    assert surface.drift_type is None


def test_teaching_audit_resolves_shepherd_dependency_writers(tmp_path: Path):
    _write_doc(
        tmp_path,
        "```bash\n"
        "yoke shepherd dependency-add YOK-20 YOK-10 idea "
        "--gate-point coordination_only --rationale independent\n"
        "yoke shepherd dependency-update YOK-20 YOK-10 "
        "--match-gate-point activation --satisfaction fact:merged\n"
        "yoke shepherd dependency-remove YOK-20 YOK-10\n"
        "```\n",
    )
    audit = inventory.generate_teaching_audit(repo_root=tmp_path)
    by_command = {row.command_form: row for row in audit.surfaces}
    assert by_command["yoke shepherd dependency-add"].function_id == (
        "shepherd.dependency_add.run"
    )
    assert by_command["yoke shepherd dependency-update"].function_id == (
        "shepherd.dependency_update.run"
    )
    assert by_command["yoke shepherd dependency-remove"].function_id == (
        "shepherd.dependency_remove.run"
    )
    assert {row.drift_type for row in by_command.values()} == {None}


def test_teaching_audit_flags_unresolved_yoke_command(tmp_path: Path):
    _write_doc(tmp_path, "`yoke nope nope`\n")
    audit = inventory.generate_teaching_audit(repo_root=tmp_path)
    surface = _only_surface(audit)
    assert surface.resolution == "unresolved"
    assert surface.drift_type == teaching.DRIFT_UNRESOLVED_YOKE


def test_teaching_audit_flags_unsanctioned_internal_module(tmp_path: Path):
    _write_doc(tmp_path, "`python3 -m yoke_core.domain.not_a_boundary --flag`\n")
    audit = inventory.generate_teaching_audit(repo_root=tmp_path)
    surface = _only_surface(audit)
    assert surface.kind == "python_module"
    assert surface.resolution == "unresolved"
    assert surface.drift_type == teaching.DRIFT_UNSANCTIONED_INTERNAL


def test_teaching_audit_accepts_db_router_query_as_break_glass(tmp_path: Path):
    _write_doc(
        tmp_path,
        "`python3 -m yoke_core.cli.db_router query \"SELECT 1\"`\n",
    )

    audit = inventory.generate_teaching_audit(repo_root=tmp_path)

    surface = _only_surface(audit)
    assert surface.kind == "python_module"
    assert surface.resolution == "permanent"
    assert surface.reason == "operator_break_glass"
    assert surface.drift_type is None


def test_teaching_audit_recognizes_db_read_after_cli_registration(
    tmp_path: Path,
):
    _write_doc(tmp_path, "`yoke db read \"SELECT 1\"`\n")

    audit = inventory.generate_teaching_audit(repo_root=tmp_path)

    surface = _only_surface(audit)
    assert surface.command_form == "yoke db read"
    assert surface.resolution == "registered"
    assert surface.drift_type is None


def test_teaching_audit_ignores_prose_mentions(tmp_path: Path):
    _write_doc(tmp_path, "The yoke CLI owns Yoke command routing.\n")

    audit = inventory.generate_teaching_audit(repo_root=tmp_path)

    assert audit.surfaces == ()


def test_teaching_audit_reports_live_commands_missing_from_teaching(tmp_path: Path):
    _write_doc(tmp_path, "`yoke items get 1`\n")

    audit = inventory.generate_teaching_audit(repo_root=tmp_path)

    missing = {row.command_form: row for row in audit.missing}
    assert "yoke claims work acquire" in missing
    assert missing["yoke claims work acquire"].drift_type == (
        teaching.DRIFT_MISSING_REGISTERED
    )
    assert "yoke board art variant create" in missing
    assert missing["yoke board art variant create"].drift_type == (
        teaching.DRIFT_MISSING_TOOL_SHAPED
    )


def test_teaching_audit_uses_smoke_runner_for_stale_argument_shape(tmp_path: Path):
    _write_doc(tmp_path, "```bash\nyoke items get\n```\n")

    audit = inventory.generate_teaching_audit(
        repo_root=tmp_path,
        smoke_yoke=lambda recipe: (False, "items.get.run", "cli_main exit=2"),
    )

    surface = _only_surface(audit)
    assert surface.command_form == "yoke items get"
    assert surface.drift_type == teaching.DRIFT_STALE_ARGUMENT_SHAPE
    assert surface.smoke_error == "cli_main exit=2"


def test_teaching_audit_skips_client_local_writer_smoke(tmp_path: Path):
    _write_doc(tmp_path, "```bash\nyoke board rebuild --force\n```\n")

    audit = inventory.generate_teaching_audit(
        repo_root=tmp_path,
        smoke_yoke=lambda recipe: (False, None, "cli_main exit=1"),
    )

    surface = _only_surface(audit)
    assert surface.command_form == "yoke board rebuild"
    assert surface.drift_type is None


def test_teaching_audit_accepts_top_level_and_global_flag_commands(tmp_path: Path):
    _write_doc(tmp_path, "`yoke --version`\n`sudo --nope`\n`yoke --env stage status`\n")

    audit = inventory.generate_teaching_audit(repo_root=tmp_path)

    by_recipe = {row.recipe: row for row in audit.surfaces}
    assert by_recipe["yoke --version"].resolution == "top_level"
    assert by_recipe["yoke --version"].drift_type is None
    assert by_recipe["yoke --env stage status"].command_form == "yoke status"
    assert by_recipe["yoke --env stage status"].drift_type is None


def test_teaching_audit_accepts_inline_namespace_and_skill_router_references(
    tmp_path: Path,
):
    _write_doc(tmp_path, "`yoke qa`\n`sudo --nope`\n`yoke idea --help`\n")

    audit = inventory.generate_teaching_audit(repo_root=tmp_path)

    by_recipe = {row.recipe: row for row in audit.surfaces}
    assert by_recipe["yoke qa"].resolution == "namespace_prefix"
    assert by_recipe["yoke qa"].drift_type is None
    assert by_recipe["yoke idea --help"].resolution == "skill_router"
    assert by_recipe["yoke idea --help"].drift_type is None


def test_markdown_renderer_can_include_teaching_audit(tmp_path: Path):
    _write_doc(tmp_path, "`yoke nope nope`\n")
    rows = tuple(inventory.generate_inventory(repo_root=REPO_ROOT))
    audit = inventory.generate_teaching_audit(repo_root=tmp_path)

    body = inventory.render_markdown(rows, teaching_audit=audit)

    assert "## taught-recipe surface audit\n" in body
    assert teaching.DRIFT_UNRESOLVED_YOKE in body
    assert "yoke nope nope" in body


def _write_doc(root: Path, body: str) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True)
    docs.joinpath("recipe.md").write_text(body, encoding="utf-8")


def _only_surface(audit: teaching.TeachingAudit) -> teaching.TaughtSurface:
    assert len(audit.surfaces) == 1
    return audit.surfaces[0]
