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
    assert len(rendered) <= 1500
    assert rendered.count("gpt-5.6-sol") == 1
    assert "ELIGIBLE RELAYS" not in rendered
    assert "MACHINES WEIGHED" not in rendered
    assert "Model" in rendered
    assert "gpt-5.6-sol" in rendered
    assert "Effort" in rendered
    assert "high" in rendered
    assert "Context tokens" in rendered
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


def test_launch_preview_names_where_each_carried_knob_came_from() -> None:
    output = io.StringIO()

    write_launch_result(
        {
            "outcome": "assigned",
            "requested_surface": "codex-cli",
            "requested_model": None,
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
            "context_window_tokens": 1_000_000,
            "model_source": "level SENIOR option",
            "reasoning_effort_source": "level SENIOR option",
            "context_window_source": "vendor default",
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
    assert "Effective model" in rendered
    assert "gpt-5.6-sol" in rendered
    assert "level SENIOR option" in rendered
    assert "Effective effort" in rendered
    assert "xhigh" in rendered
    assert "vendor default" in rendered
    assert "Effective context tokens" in rendered
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


_PLACEMENT = {
    "level": "SENIOR",
    "levels_source": "universe",
    "rule": "most_headroom",
    "reason": "most headroom: claude-cli claude-opus-5-5 high on m1 at 80%",
    "chosen": {"label": "claude-cli claude-opus-5-5 high on m1"},
    "candidates": [
        {
            "label": "claude-cli claude-opus-5-5 high on m1",
            "pools": [
                {
                    "window": "weekly \u00b7 Opus",
                    "remaining_percent": 60.0,
                    "headroom_percent": 80.0,
                }
            ],
            "headroom_percent": 80.0,
            "live_workers": 1,
            "blocked": None,
            "chosen": True,
        },
        {
            "label": "codex-cli gpt-6-sol high on m1",
            "pools": [],
            "headroom_percent": None,
            "live_workers": 0,
            "blocked": "weekly pool exhausted (resets unknown)",
            "chosen": False,
        },
    ],
}


def test_a_level_preview_names_the_level_its_choice_and_every_option() -> None:
    output = io.StringIO()

    write_launch_preview(
        {
            "outcome": "assigned",
            "requested_surface": "claude-cli",
            "selected_surface": "claude-cli",
            "launchable": True,
            "eligible_relays": [],
            "level_placement": _PLACEMENT,
        },
        output,
    )

    rendered = output.getvalue()
    assert "SENIOR (universe)" in rendered
    assert "Level option" in rendered
    assert "Level choice" in rendered
    assert "most headroom" in rendered
    assert "LEVEL OPTIONS WEIGHED" in rendered
    assert "codex-cli gpt-6-sol high on m1" in rendered
    assert "pool exhausted" in rendered
    assert "Headroom on other surfaces" not in rendered


def test_a_level_preview_with_no_capacity_says_so() -> None:
    output = io.StringIO()

    write_launch_preview(
        {
            "outcome": "level_no_capacity",
            "launchable": False,
            "eligible_relays": [],
            "level_placement": {**_PLACEMENT, "chosen": None, "rule": None},
        },
        output,
    )

    assert "none had capacity" in output.getvalue()


def test_a_level_launch_record_shows_its_selection_and_placement() -> None:
    output = io.StringIO()

    write_launch_result(
        {
            "launch": {
                "launch_id": "launch-1",
                "selection": "level",
                "requested_level": "SENIOR",
                "level_placement": _PLACEMENT,
                "requested_surface": "claude-cli",
                "selected_surface": "claude-cli",
            }
        },
        output,
    )

    rendered = output.getvalue()
    assert "Selection" in rendered
    assert "level" in rendered
    assert "SENIOR (universe)" in rendered
    assert "LEVEL OPTIONS WEIGHED" in rendered


def test_an_override_launch_record_shows_no_level_rows() -> None:
    output = io.StringIO()

    write_launch_result(
        {
            "launch": {
                "launch_id": "launch-1",
                "selection": "override",
                "level_placement": None,
                "requested_surface": "cursor-cli",
            }
        },
        output,
    )

    rendered = output.getvalue()
    assert "override" in rendered
    assert "Level option" not in rendered
    assert "LEVEL OPTIONS WEIGHED" not in rendered
