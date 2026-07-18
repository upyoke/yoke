"""Focused installer recipe templates extracted from the coordinator suite."""

from yoke_core.tools import installer_live_tui_coordinator as coordinator


def test_ambient_indexes_recipe_uses_installer_owned_sources() -> None:
    recipe = coordinator._known_recipe_template(  # noqa: SLF001
        "INSTALL-UV-013",
        "https://api.stage.upyoke.com",
    )

    assert isinstance(recipe, dict)
    assert "UV_DEFAULT_INDEX=" in recipe["command"]
    assert "UV_INDEX=https://ambient.invalid/simple/" in recipe["command"]
    assert "no_text:ambient.invalid" in recipe["post_checks"]
