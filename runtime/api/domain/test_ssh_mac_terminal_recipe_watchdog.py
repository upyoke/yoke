"""Coverage for the interactive recipe lifetime backstop."""

from __future__ import annotations

from yoke_core.domain.ssh_mac_terminal_recipe_watchdog import (
    wrapped_entry_surface,
)


def test_wrapped_entry_surface_replaces_unbounded_sleep_tail() -> None:
    wrapped = wrapped_entry_surface(
        "yoke onboard --post-install",
        "/tmp/yoke-qa-deadbeef.exit",
        watchdog_seconds=30,
    )

    assert "sleep 600" not in wrapped
    assert "yoke onboard --post-install" in wrapped
    assert "yk_left=30" in wrapped
    assert "yoke_reap_tree" in wrapped
    assert "/tmp/yoke-qa-deadbeef.exit" in wrapped
