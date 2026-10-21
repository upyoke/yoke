"""Generated approval guidance teaches one rule: the agent approves codes.

The agent approves machine and GitHub codes; only password entry goes to a
person. A surface that still hands the code itself to the person teaches the
retired rule.
"""

from __future__ import annotations

import pytest

from yoke_cli.config import setup_agent_response
from yoke_cli.config.onboard_github_copy import machine_github_agent_guidance
from yoke_cli.config.setup_prompt import SetupHuman

RETIRED_PHRASES = (
    "human click",
    "pass the browser link to the person",
    "finish in their browser",
    "show the person this link",
    "ask them to approve in their browser",
    "person approves their own machine",
)


def _human() -> SetupHuman:
    return SetupHuman(instructions="Open the link.", url="https://x.test", user_code="K7F2")


def _generated_surfaces() -> dict[str, str]:
    pending = setup_agent_response.approval_pending(
        "connect", "connect.hosted_machine_approval", _human(), instead=""
    )
    shown = setup_agent_response.browser("github", "github.app", _human())
    return {
        "approval_pending guidance": pending["guidance"],
        "browser guidance": shown["guidance"],
        "machine GitHub guidance": machine_github_agent_guidance("create-repo"),
    }


@pytest.mark.parametrize("name", sorted(_generated_surfaces()))
def test_surface_never_teaches_the_retired_approval_rule(name: str) -> None:
    text = " ".join(_generated_surfaces()[name].lower().split())
    found = [phrase for phrase in RETIRED_PHRASES if phrase in text]
    assert not found, f"{name} still teaches {found}"


def test_waiting_browser_step_names_the_agent_route() -> None:
    guidance = _generated_surfaces()["approval_pending guidance"]
    assert "yoke machines approve CODE" in guidance
    assert "Only a password entry goes to the person" in guidance
