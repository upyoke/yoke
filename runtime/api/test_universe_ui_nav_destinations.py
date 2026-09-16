"""The nav roster every route resolves against."""

from __future__ import annotations

from importlib.resources import files


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
    # Grouped as the sidebar groups them: focus, then settings, then the
    # diagnostics drawer.
    for destination in (
        "strategy", "frontier", "shipping", "machines", "sessions", "inbox",
        "organization", "workflows", "projects", "github", "actors",
        "members", "billing",
        "items", "deployments", "environments",
        "databases", "qa-methods", "qa-plans",
        "qa-activity", "capabilities", "packs", "architecture", "messages",
        "events", "doctor", "ouroboros",
    ):
        assert f'id: "{destination}"' in page_module, destination
    assert 'id: "board"' not in page_module
    # Flows is a tab of Deployments rather than a destination of its own,
    # and carries the same `id:` shape there.
    assert 'id: "flows", label: "Flows"' in page_module
    # The Overview that stacked Strategy, Frontier and Shipping is gone, and
    # Project settings was absorbed by the Projects row that opens it.
    for absorbed in ("overview", "project", "delivery", "qa"):
        assert f'id: "{absorbed}"' not in page_module, absorbed
    # Execution instructions are edited inside the workflows page; a nav
    # entry of their own would lead to a screen that no longer exists.
    assert 'id: "instructions"' not in page_module
    # Host-fed screens sit in the same flat nav arc as every other view, and
    # the flag ties each entry's visibility to a host-supplied section.
    for host_fed in ("members", "billing"):
        entry_start = page_module.index(f'id: "{host_fed}"')
        entry_end = page_module.index("}", entry_start)
        assert "hostFed: true" in page_module[entry_start:entry_end], host_fed
