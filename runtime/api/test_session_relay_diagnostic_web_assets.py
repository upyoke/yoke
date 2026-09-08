"""Web visibility for machine-user-local native relay diagnostics."""

from __future__ import annotations

from importlib.resources import files


def test_session_failure_views_show_owner_local_diagnostic_recipe() -> None:
    static_root = files("yoke_core.ui").joinpath("static")
    helper = static_root.joinpath("session_relay_diagnostic_view.js").read_text()
    messages = static_root.joinpath("universe_session_messages.js").read_text()
    # Launch detail — timeline, evidence, and the diagnostic recipe — renders
    # from the detail card the list expands into, not from the list itself.
    launch_detail = static_root.joinpath("session_launch_detail_card.js").read_text()
    launches = static_root.joinpath("universe_session_launches.js").read_text()
    styles = static_root.joinpath("universe_session_control.css").read_text()

    for field in (
        "native_diagnostic_ref",
        "native_diagnostic_command",
        "machine_id",
        "relay_id",
        "native_error_class",
        "native_error_step",
        "diagnostic_availability",
        "diagnostic_expires_at",
    ):
        assert field in helper
    assert "appendRelayDiagnostic" in messages
    assert "attempt.evidence" in messages
    assert "appendRelayDiagnostic" in launch_detail
    assert "appendLaunchDetail" in launches
    assert "session-relay-diagnostic-command" in styles
    assert "user-select: all" in styles
    assert "Local detail unavailable." in helper
