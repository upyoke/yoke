"""Human output for launch-model verification timing."""

from __future__ import annotations

import io

from yoke_cli.commands.adapters.session_control_launch_output import (
    write_launch_result,
)
from yoke_cli.commands.adapters.session_control_launch_preview_output import (
    write_launch_preview,
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
            "reasoning_effort": "xhigh",
            "context_window_tokens": 1_000_000,
            "model_source": "machine-roomy preferred_session_models.codex-cli",
            "reasoning_effort_source": (
                "machine-roomy preferred_session_reasoning_efforts.codex-cli"
            ),
            "context_window_source": (
                "machine-roomy preferred_session_models.codex-cli"
            ),
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
    assert "Effort this launch would carry" in rendered
    assert "xhigh" in rendered
    assert "machine-roomy preferred_session_reasoning_efforts.codex-cli" in rendered
    assert "Context tokens this launch would carry" in rendered
    assert "1000000" in rendered
    assert "at session registration" in rendered
    assert "MACHINES WEIGHED" in rendered
    assert "240% (rolling 5h · all models)" in rendered
    assert "most codex-cli headroom; chose machine-roomy" in rendered


def _preview_with_pool(pool: dict | None) -> str:
    output = io.StringIO()
    write_launch_preview(
        {
            "outcome": "assigned",
            "requested_surface": "cursor-cli",
            "requested_model": "cursor-grok-4.6-high",
            "selected_surface": "cursor-cli",
            "launchable": True,
            "eligible_relays": [],
            "machine_candidates": [
                {
                    "machine_id": "machine-a",
                    "hostname": "host-a",
                    "surface": "cursor-cli",
                    "headroom_percent": 40.0,
                    "headroom_window": "monthly · Cursor Models",
                    "model_pool": pool,
                    "owned_by_requester": True,
                    "may_use": True,
                    "selected": True,
                }
            ],
        },
        output,
    )
    return output.getvalue()


def test_the_weighed_machines_name_the_requested_model_billing_pool() -> None:
    rendered = _preview_with_pool(
        {
            "pool": "Cursor Models",
            "remaining_percent": 62.0,
            "exhausted": False,
            "reason": "the pool still has headroom",
        }
    )

    assert "REQUESTED MODEL POOL" in rendered
    assert "Cursor Models: 62% left" in rendered


def test_an_exhausted_pool_says_so_rather_than_printing_zero_percent() -> None:
    rendered = _preview_with_pool(
        {
            "pool": "Cursor Models",
            "remaining_percent": 0.0,
            "exhausted": True,
            "reason": None,
        }
    )

    assert "Cursor Models: exhausted" in rendered


def test_an_unreadable_pool_names_its_reason_instead_of_a_number() -> None:
    rendered = _preview_with_pool(
        {
            "pool": "Cursor Models",
            "remaining_percent": None,
            "exhausted": False,
            "reason": "the pool's meter is unreadable",
        }
    )

    assert "Cursor Models: unreadable" in rendered
