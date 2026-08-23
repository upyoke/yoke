"""Human output for launch-model verification timing."""

from __future__ import annotations

import io

from yoke_cli.commands.adapters.session_control_launch_output import (
    write_launch_result,
)


def test_launch_preview_says_model_is_verified_at_registration() -> None:
    output = io.StringIO()

    write_launch_result(
        {
            "outcome": "assigned",
            "requested_surface": "codex-desktop",
            "requested_model": "gpt-5.6-sol",
            "selected_surface": "codex-desktop",
            "launchable": True,
            "eligible_relays": [],
        },
        output,
    )

    rendered = output.getvalue()
    assert "Requested model" in rendered
    assert "gpt-5.6-sol" in rendered
    assert "Model verification" in rendered
    assert "at session registration" in rendered
