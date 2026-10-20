"""Every approval surface teaches one rule: the agent approves codes.

The agent approves machine and GitHub codes; only password entry goes to a
person. A surface that still hands the code itself to the person teaches the
retired rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.config import setup_agent_response
from yoke_cli.config.onboard_github_copy import machine_github_agent_guidance
from yoke_cli.config.setup_prompt import SetupHuman

ROOT = Path(__file__).resolve().parents[2]
FILE_SURFACES = (
    "packages/yoke-contracts/src/yoke_contracts/global_skill/SKILL.md",
    "docs/public/start/agent-setup.md",
    "docs/teaching/model/surfaces/machine-admission.json",
    "docs/teaching/model/surfaces/setup-agent.json",
)
RETIRED_PHRASES = (
    "human click",
    "pass the browser link to the person",
    "finish in their browser",
    "show the person this link",
    "ask them to approve in their browser",
    "person approves their own machine",
)
RULE = "only password entry goes to a person"


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


def _surfaces() -> dict[str, str]:
    files = {path: (ROOT / path).read_text(encoding="utf-8") for path in FILE_SURFACES}
    return {**files, **_generated_surfaces()}


@pytest.mark.parametrize("name", sorted(_surfaces()))
def test_surface_never_teaches_the_retired_approval_rule(name: str) -> None:
    text = " ".join(_surfaces()[name].lower().split())
    found = [phrase for phrase in RETIRED_PHRASES if phrase in text]
    assert not found, f"{name} still teaches {found}"


@pytest.mark.parametrize("name", sorted(FILE_SURFACES))
def test_file_surface_states_the_rule(name: str) -> None:
    text = " ".join((ROOT / name).read_text(encoding="utf-8").lower().split())
    assert RULE in text, f"{name} must state: {RULE}"


def test_waiting_browser_step_names_the_agent_route() -> None:
    guidance = _generated_surfaces()["approval_pending guidance"]
    assert "yoke machines approve CODE" in guidance
    assert "Only a password entry goes to the person" in guidance
