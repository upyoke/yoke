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


def test_javascript_module_graph_is_in_closed_asset_roster():
    static_root = files("yoke_core.ui").joinpath("static")
    for module_name in ("app.js", "contract.js"):
        source = static_root.joinpath(module_name).read_text(encoding="utf-8")
        imports = re.findall(r'from "\./([^\"]+\.js)"', source)
        assert imports
        assert set(imports) <= set(ui_server.ASSET_CONTENT_TYPES)


def test_unknown_asset_is_404(ui_client):
    response = ui_client.get(f"/assets/nope.txt?token={TOKEN}")
    assert response.status_code == 404


def test_static_assets_ship_as_package_resources():
    static_root = files("yoke_core.ui").joinpath("static")
    for asset_name in ui_server.ASSET_CONTENT_TYPES:
        assert static_root.joinpath(asset_name).is_file(), asset_name


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
    for asset_name in ("app.js", "app.css", "theme.css", "favicon.svg"):
        assert f"./assets/{asset_name}" in shell


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
    assert {
        source_value.group(1),
        declaration_value.group(1),
        runtime_value.group(1),
    } == {"1"}


def test_page_module_wires_the_workbench_shell():
    page_module = files("yoke_core.ui").joinpath("static", "app.js").read_text()
    for reference in (
        "export function mountUniverseApp",
        "projects.list",
        "strategy.doc.list",
        "items.list.run",
        '{ label: "title", value: (doc) => doc.title }',
    ):
        assert reference in page_module, reference


def test_every_nav_destination_is_routable_and_scoped():
    """Each nav entry is a real route from day one: it declares its scope and
    either renders rows or states what it will be."""
    page_module = files("yoke_core.ui").joinpath("static", "app.js").read_text()
    for destination in (
        "overview", "inbox", "strategy", "frontier", "items", "board",
        "sessions", "delivery", "qa", "workflows", "capabilities", "events",
        "doctor", "ouroboros", "projects", "access", "templates", "github",
        "project-settings", "universe-settings",
    ):
        assert f'id: "{destination}"' in page_module, destination
    # Hosted chrome arrives through the platform's slot, never the nav roster.
    for hosted in ("members", "billing"):
        assert f'id: "{hosted}"' not in page_module, hosted
