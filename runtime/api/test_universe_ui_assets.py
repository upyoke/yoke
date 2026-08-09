"""Static-resource and mount-contract coverage for the universe UI bundle."""

from __future__ import annotations

import re
from importlib.resources import files

import pytest
from fastapi.testclient import TestClient

from yoke_core.ui import server as ui_server


TOKEN = "test-session-token-value"


@pytest.fixture()
def ui_client():
    with TestClient(ui_server.create_ui_app(TOKEN)) as client:
        yield client


def test_known_assets_serve_with_content_types(ui_client):
    for asset_name, content_type in ui_server.ASSET_CONTENT_TYPES.items():
        response = ui_client.get(f"/assets/{asset_name}?token={TOKEN}")
        assert response.status_code == 200, asset_name
        assert response.headers["content-type"] == content_type


def test_assets_and_shell_are_served_with_revalidation_header(ui_client):
    # `no-cache` (revalidate, not `no-store`): browsers must recheck the
    # server after an upgrade instead of running stale modules from cache.
    for asset_name in ui_server.ASSET_CONTENT_TYPES:
        response = ui_client.get(f"/assets/{asset_name}?token={TOKEN}")
        assert response.status_code == 200, asset_name
        assert response.headers["cache-control"] == "no-cache", asset_name
    shell = ui_client.get(f"/?token={TOKEN}")  # follows the 303
    assert shell.status_code == 200
    assert shell.headers["cache-control"] == "no-cache"


def test_javascript_module_graph_is_in_closed_asset_roster():
    static_root = files("yoke_core.ui").joinpath("static")
    roster = set(ui_server.ASSET_CONTENT_TYPES)
    for module_name in sorted(name for name in roster if name.endswith(".js")):
        source = static_root.joinpath(module_name).read_text(encoding="utf-8")
        imports = re.findall(
            r"""(?:from\s+|import\s*)["']\./([^"']+\.js)["']""",
            source,
        )
        assert set(imports) <= roster, module_name


def test_stylesheet_import_graph_is_in_closed_asset_roster():
    static_root = files("yoke_core.ui").joinpath("static")
    for asset_name in ui_server.ASSET_CONTENT_TYPES:
        if not asset_name.endswith(".css"):
            continue
        source = static_root.joinpath(asset_name).read_text(encoding="utf-8")
        imports = re.findall(r'@import url\("\./([^"]+\.css)"\)', source)
        assert set(imports) <= set(ui_server.ASSET_CONTENT_TYPES)


def test_unknown_asset_is_404(ui_client):
    response = ui_client.get(f"/assets/nope.txt?token={TOKEN}")
    assert response.status_code == 404


def test_static_assets_ship_as_package_resources():
    static_root = files("yoke_core.ui").joinpath("static")
    for asset_name in ui_server.ASSET_CONTENT_TYPES:
        assert static_root.joinpath(asset_name).is_file(), asset_name


def test_each_css_asset_is_a_self_contained_stylesheet():
    """Imported stylesheets cannot continue a rule across file boundaries."""
    static_root = files("yoke_core.ui").joinpath("static")
    for asset_name in ui_server.ASSET_CONTENT_TYPES:
        if not asset_name.endswith(".css"):
            continue
        source = static_root.joinpath(asset_name).read_text()
        assert source.count("{") == source.count("}"), asset_name

    chrome = static_root.joinpath("universe_chrome.css").read_text()
    panel_rule = re.search(
        r"\.universe-app-root \.panel\s*\{(?P<body>[^}]*)\}",
        chrome,
        re.DOTALL,
    )
    assert panel_rule is not None
    for declaration in (
        "background:",
        "border:",
        "border-radius:",
        "overflow:",
        "margin-bottom:",
        "transition:",
    ):
        assert declaration in panel_rule.group("body"), declaration


def test_phone_shell_gives_the_route_the_full_viewport():
    static_root = files("yoke_core.ui").joinpath("static")
    chrome = static_root.joinpath("universe_chrome.css").read_text()
    controls = static_root.joinpath("universe_shell_controls.css").read_text()

    phone_rules = chrome.split("@media (max-width: 720px)", 1)[1]
    assert "grid-template-columns: minmax(0, 1fr)" in phone_rules
    assert ".universe-app-root .shell > .sidenav" in phone_rules
    assert "flex-direction: row" in phone_rules
    assert "overflow-x: auto" in phone_rules
    assert ".universe-app-root .workbench-body" in phone_rules
    assert "grid-column: 1" in phone_rules

    compact_controls = controls.split("@media (max-width: 560px)", 1)[1]
    assert ".universe-app-root .header-search" in compact_controls
    assert "display: none" in compact_controls


def test_page_module_exports_the_mount_contract():
    page_module = files("yoke_core.ui").joinpath("static", "app.js").read_text()
    assert "export function mountUniverseApp(rootNode, options = {})" in page_module
    assert "options.client || createHttpFunctionClient()" in page_module
    assert 'new URL("./yoke-wordmark.svg", import.meta.url)' in page_module
    assert 'fetch("/assets/' not in page_module


def test_shell_static_references_are_host_prefix_safe():
    shell = files("yoke_core.ui").joinpath("static", "index.html").read_text()
    assert 'class="local-universe-page"' in shell
    assert '="/assets/' not in shell
    for asset_name in (
        "app.js",
        "app.css",
        "shell.css",
        "theme.css",
        "favicon.svg",
    ):
        assert f"./assets/{asset_name}" in shell


def test_hosted_frame_harness_mirrors_the_platform_slot_shapes():
    """The harness page exists so the hosted frame is verifiable without a
    pin. It only does that job if its sample chrome wears the exact class
    names the platform's hosted shell injects — a harness with invented
    names verifies a frame nobody ships."""
    harness = (
        files("yoke_core.ui")
        .joinpath(
            "static",
            "hosted-frame-harness.html",
        )
        .read_text()
    )
    for platform_marker in (
        "hosted-org-switcher",
        "hosted-user-menu",
        'dataset.platformSlot = "github-connection"',
    ):
        assert platform_marker in harness, platform_marker
    assert "hosted-org-links" not in harness
    assert "hosted-github-link" not in harness
    assert "hosted-tenant-replacement-link" not in harness
    # Every mount slot the platform fills is occupied here too.
    for slot_name in (
        "topbarStart",
        "topbarEnd",
        "contentBefore",
        "contentAfter",
    ):
        assert f"{slot_name}:" in harness, slot_name
    assert "navigationEnd:" not in harness
    # The page names itself a harness so it cannot pass for the product,
    # and mirrors Platform's identity boundary: topbarEnd owns identity, so
    # the mounted app must not add a duplicate currentActor chip.
    assert "Hosted-frame harness" in harness
    assert "currentActor" not in harness
    assert 'memberDirectory: { "2": "ben", "5": "dana" }' in harness
    assert "Move universe" in harness


def test_typed_mount_contract_and_declaration_emit_ship():
    ui_root = files("yoke_core.ui")
    contract_root = ui_root.joinpath("contracts")
    source = contract_root.joinpath("universe-app.ts").read_text()
    declaration = contract_root.joinpath("universe-app.d.ts").read_text()
    runtime_version = ui_root.joinpath("static", "contract-version.js").read_text()
    assert contract_root.joinpath("tsconfig.json").is_file()
    for reference in (
        "UniverseFunctionClient",
        "UniverseCapabilities",
        "UniverseAction",
        "UniverseAppSlots",
        "UniverseAppMount",
        "mountUniverseApp",
    ):
        assert reference in source
        assert reference in declaration
    source_value = re.search(r"UNIVERSE_APP_CONTRACT_VERSION = (\d+) as const", source)
    declaration_value = re.search(r"UNIVERSE_APP_CONTRACT_VERSION: (\d+)", declaration)
    runtime_value = re.search(r"UNIVERSE_APP_CONTRACT_VERSION = (\d+)", runtime_version)
    assert source_value is not None
    assert declaration_value is not None
    assert runtime_value is not None
    # The three emits must agree on the version; which number it is belongs to
    # the TypeScript source, not to this assertion. Pinning the literal here
    # would fail every bump on principle.
    assert (
        len(
            {
                source_value.group(1),
                declaration_value.group(1),
                runtime_value.group(1),
            }
        )
        == 1
    )


def test_page_module_wires_the_workbench_shell():
    """The mount and the roster read live in the shell; each view's own read
    lives with that view. Assert each against the module that owns it, so a
    reference moving house fails loudly rather than silently passing."""
    static_root = files("yoke_core.ui").joinpath("static")
    shell = static_root.joinpath("app.js").read_text()
    for reference in ("export function mountUniverseApp", "projects.list"):
        assert reference in shell, reference

    # Header search queries items on the server so the whole backlog stays
    # reachable; only the session arm still filters a cached roster.
    controls = static_root.joinpath("universe_shell_controls.js").read_text()
    for reference in ("items.search.run", "sessions.list"):
        assert reference in controls, reference

    view_references = {
        "universe_views_strategy.js": (
            "strategy.surface.list",
            "renderStrategyTable",
            '"Purpose / ancestry"',
        ),
        "universe_views_items.js": ("items.overview.list",),
        "item_detail_loader.js": ("items.detail.get",),
        "item_view_details.js": ("epic_tasks.list.run",),
        "universe_views_events.js": ("events.query.run",),
        "universe_views_delivery.js": ("deployment_runs.list",),
        "universe_views_delivery_inventory.js": (
            "projects.infrastructure.list",
            "projects.environment_settings.get",
            "projects.capabilities.list",
            "deployment_runs.list",
        ),
        "universe_views_sessions.js": ("sessions.list",),
        "universe_views_doctor.js": ("doctor.last_run.get",),
        "universe_views_frontier.js": ("frontier.list",),
        "universe_views_capabilities.js": ("projects.capabilities.list",),
    }
    for module_name, references in view_references.items():
        view = static_root.joinpath(module_name).read_text()
        for reference in references:
            assert reference in view, f"{module_name}: {reference}"

    workflows_view = static_root.joinpath(
        "universe_views_workflows.js",
    ).read_text()
    assert "workflows.definition.get" in workflows_view

    github_view = static_root.joinpath("universe_views_github.js").read_text()
    assert "projects.github_binding.status" in github_view


def test_delivery_facets_keep_wide_tables_scrollable_on_compact_screens():
    css = (
        files("yoke_core.ui")
        .joinpath("static", "universe_secondary_activity.css")
        .read_text()
    )

    assert "@media (max-width: 760px)" in css
    assert ".delivery-facet-panel .table-wrap" in css
    assert "touch-action: pan-x" in css
    assert ".delivery-facet-panel .table-wrap > table" in css
    assert "min-width: 660px" in css
    assert ".delivery-run-stages" in css
    assert ".delivery-flow-pipeline" in css

    secondary_css = (
        files("yoke_core.ui")
        .joinpath("static", "universe_secondary_views.css")
        .read_text()
    )
    assert ".packs-stack" in secondary_css
    assert ".pack-available-row" in secondary_css


def test_qa_case_table_keeps_actions_visible_in_the_prototype_split():
    css = files("yoke_core.ui").joinpath("static", "qa_details.css").read_text()

    assert ".universe-app-root .qa-case-panel-body" in css
    assert ".qa-case-panel-body .qa-case-table" in css
    assert "min-width: 100%" in css


def test_every_nav_destination_is_routable_and_scoped():
    """Each nav entry is a real route from day one: it declares its scope and
    either renders rows, states what it will be, or renders host content."""
    page_module = (
        files("yoke_core.ui")
        .joinpath(
            "static",
            "universe_destinations.js",
        )
        .read_text()
    )
    for destination in (
        "overview",
        "inbox",
        "strategy",
        "frontier",
        "items",
        "sessions",
        "delivery",
        "qa",
        "workflows",
        "capabilities",
        "events",
        "doctor",
        "ouroboros",
        "projects",
        "access",
        "members",
        "billing",
        "packs",
        "github",
        "project",
        "organization",
    ):
        assert f'id: "{destination}"' in page_module, destination
    assert 'id: "board"' not in page_module
    # Execution instructions are edited inside the workflows page; a nav
    # entry of their own would lead to a screen that no longer exists.
    assert 'id: "instructions"' not in page_module
    # Host-fed screens sit in the same flat nav arc as every other view, and
    # the flag ties each entry's visibility to a host-supplied section.
    for host_fed in ("members", "billing"):
        entry_start = page_module.index(f'id: "{host_fed}"')
        entry_end = page_module.index("}", entry_start)
        assert "hostFed: true" in page_module[entry_start:entry_end], host_fed
