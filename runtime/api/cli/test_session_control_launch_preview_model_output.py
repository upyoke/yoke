"""Human output for launch-model verification timing."""

from __future__ import annotations

import io

from yoke_cli.commands.adapters.session_control_launch_output import (
    write_launch_result,
)


def test_launch_preview_says_selection_is_verified_at_registration() -> None:
    output = io.StringIO()

    write_launch_result(
        {
            "outcome": "assigned",
            "requested_surface": "codex-desktop",
            "requested_model": "gpt-5.6-sol",
            "requested_reasoning_effort": "high",
            "requested_context_window_tokens": 1_000_000,
            "selected_surface": "codex-desktop",
            "launchable": True,
            "eligible_relays": [],
        },
        output,
    )

    rendered = output.getvalue()
    assert "Requested model" in rendered
    assert "gpt-5.6-sol" in rendered
    assert "Requested effort" in rendered
    assert "high" in rendered
    assert "Requested context tokens" in rendered
    assert "1000000" in rendered
    assert "Selection verification" in rendered
    assert "at session registration" in rendered


def test_effort_without_model_is_still_a_requested_selection() -> None:
    output = io.StringIO()

    write_launch_result(
        {
            "outcome": "assigned",
            "requested_surface": "codex-cli",
            "requested_reasoning_effort": "high",
            "selected_surface": "codex-cli",
            "launchable": True,
            "eligible_relays": [],
        },
        output,
    )

    rendered = output.getvalue()
    assert "Selection verification" in rendered
    assert "at session registration" in rendered


def test_launch_preview_names_the_machine_that_decided_an_unasked_model() -> None:
    output = io.StringIO()

    write_launch_result(
        {
            "outcome": "assigned",
            "requested_surface": "codex-cli",
            "requested_model": None,
            "model": "gpt-5.6-sol",
            "model_source": "machine-roomy preferred_session_models.codex-cli",
            "selected_surface": "codex-cli",
            "launchable": True,
            "eligible_relays": [],
            "placement_reason": "most codex-cli headroom; chose machine-roomy",
            "machine_candidates": [
                {
                    "machine_id": "machine-roomy",
                    "hostname": "roomy-host",
                    "surface": "codex-cli",
                    "headroom_percent": 240.0,
                    "headroom_window": "rolling 5h · all models",
                    "owned_by_requester": True,
                    "may_use": True,
                    "denial_reason": None,
                    "selected": True,
                }
            ],
        },
        output,
    )

    rendered = output.getvalue()
    assert "Model this launch would carry" in rendered
    assert "gpt-5.6-sol" in rendered
    assert "machine-roomy preferred_session_models.codex-cli" in rendered
    assert "at session registration" in rendered
    assert "MACHINES WEIGHED" in rendered
    assert "240% (rolling 5h · all models)" in rendered
    assert "most codex-cli headroom; chose machine-roomy" in rendered
