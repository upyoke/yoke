"""Recipe builders for the installer campaign's machine admission journeys.

The full-screen wizard journeys share their opening screens and match-code
wait; the agent journeys run ``machine_qa_setup_agent_driver``. Every case
installs the candidate, prepares the admission fixture for its mode, lets the
run perform the owner's or teammate's step through a typed gate, and proves
the universe's rows.
"""

from __future__ import annotations

from yoke_contracts.machine_authorization import MATCH_CODE_LABEL

import shlex
from typing import Any, Sequence

from yoke_core.domain.installer_campaign_plan_common import (
    FRESH_HOST,
    MACHINE_GITHUB_TEXT,
    SECRET_SAFE_POST_CHECKS,
    action,
    current_release_setup,
    terminal_case,
    terminal_recipe,
    transition,
)
from yoke_core.domain.installer_campaign_recipe_operations import operation
from yoke_core.domain.machine_qa_admission_host import (
    TEAMMATE_NAME,
    api_url,
    approver_home,
    mode_root,
)
from yoke_core.domain.machine_qa_operator_gate_contract import (
    ADMISSION_OWNER_APPROVAL,
    MACHINE_BROWSER_APPROVAL,
)
from yoke_core.domain.machine_qa_fixture_constants import YOKE_BIN
from yoke_core.domain.machine_qa_fixture_validation_admission import (
    PREPARE,
    STATE_ASSERT,
)
from yoke_core.domain.machine_qa_setup_agent_driver import REACHED

SERVER = api_url("self-hosted")
COMPANY = api_url("self-hosted-company-sign-in")
OWNER_HOME = shlex.quote(str(approver_home("self-hosted")))
LOCAL_HOME = shlex.quote(str(mode_root("local") / "home"))
TEAM_SERVER_TEXT = "Connect to your team server."
# Key hints only the full-screen wizard draws; the agent driver never prints them.
WIZARD_CHROME_TEXT = "^c quit"
ADMISSION_TEXT = "How should this machine join your team server?"
APPROVAL_TEXT = ("Sign in and approve your machine.", MATCH_CODE_LABEL)
LOCAL_NOTICE = "Reachable here only."
AGENT_REACHED = f"{REACHED} github.machine"
AGENT_DRIVER = (
    '"$(uv tool dir)/yoke-cli-releases/current/tools/yoke-cli/bin/python3" '
    "-m yoke_core.domain.machine_qa_setup_agent_driver --stop-at github.machine"
)
OWNER_STEP = (
    "the run approves the match code as the owner on this test machine: "
    f"YOKE_MACHINE_HOME={OWNER_HOME} yoke machines approve CODE."
)
INVITE_STEP = (
    f"the run issues the invite as the owner (YOKE_MACHINE_HOME={OWNER_HOME} "
    f"yoke invite '{TEAMMATE_NAME}') and types its code into the wizard."
)
COMPANY_STEP = (
    "the run approves this machine in the test machine's browser, where the "
    "company sign-in signs in as the fixture teammate."
)


def agent_gate(step: str, gate: str, completion: str, *keys: str) -> dict[str, Any]:
    """The run performs the person's step itself, then waits for *completion*."""
    return transition(
        step,
        *keys,
        operator_gate=gate,
        completion_text=(completion,),
        gate_timeout_seconds=600,
    )


def admission_case(
    key: str,
    *,
    mode: str,
    expect: str,
    entry: str,
    actions: Sequence[dict[str, Any]],
    expected_text: Sequence[str],
    captures: Sequence[str],
    required: str,
    instructions: str,
    outcome: str,
    execution_mode: str = "terminal",
) -> dict[str, Any]:
    config = terminal_recipe(
        actions=actions,
        expected_text=expected_text,
        capture_checkpoints=captures,
        notes=instructions,
        setup_operations=[
            *current_release_setup(key, clear_auth=True, path_ready=True),
            operation(PREPARE, mode=mode),
        ],
        post_checks=SECRET_SAFE_POST_CHECKS,
        execution_mode=execution_mode,
    )
    config["post_state_assertions"] = [
        operation(STATE_ASSERT, mode=mode, expect=expect)
    ]
    return terminal_case(
        0,
        key,
        "terminal-check",
        instructions=instructions,
        expected_outcome=outcome,
        method_config=config,
        entry_surface=entry,
        required_completion=required,
        host_baselines=(FRESH_HOST,),
    )


def wizard_start() -> list[dict[str, Any]]:
    return [
        action(
            "team-server", ready_text=(TEAM_SERVER_TEXT,), ready_timeout_seconds=180
        ),
        transition("team-server-url", "Enter", ready_text=(TEAM_SERVER_TEXT,)),
    ]


def wizard_code_wait(step: str) -> list[dict[str, Any]]:
    """Wait for the match code, then approve it as the owner."""
    return [
        action("match-code", ready_text=APPROVAL_TEXT, ready_timeout_seconds=60),
        transition("start-waiting", "Enter", ready_text=APPROVAL_TEXT),
        agent_gate(step, ADMISSION_OWNER_APPROVAL, MACHINE_GITHUB_TEXT[0]),
        action("machine-github"),
    ]


def wizard_browser_approval(step: str) -> list[dict[str, Any]]:
    """Wait for the match code, then approve it in the wizard-opened browser tab."""
    return [
        action(
            "match-code", ready_text=(*APPROVAL_TEXT, "Open:"), ready_timeout_seconds=60
        ),
        agent_gate(step, MACHINE_BROWSER_APPROVAL, MACHINE_GITHUB_TEXT[0], "Enter"),
        action("machine-github"),
    ]


def wizard_case(key, *, mode, expect, actions, captures, instructions, outcome):
    connect = COMPANY if mode == "self-hosted-company-sign-in" else SERVER
    return admission_case(
        key,
        mode=mode,
        expect=expect,
        entry=f"{YOKE_BIN} setup --tui --connect {connect}",
        actions=actions,
        expected_text=(TEAM_SERVER_TEXT, *MACHINE_GITHUB_TEXT),
        captures=captures,
        required="machine-github",
        instructions=instructions,
        outcome=outcome,
    )


def agent_case(key, *, mode, expect, answers, actions, captures, instructions, outcome):
    connect = COMPANY if mode == "self-hosted-company-sign-in" else SERVER
    flags = " ".join(
        [
            *(["--open-link"] if mode == "self-hosted-company-sign-in" else []),
            *(f"--answer {shlex.quote(answer)}" for answer in answers),
        ]
    )
    return admission_case(
        key,
        mode=mode,
        expect=expect,
        entry=f"{AGENT_DRIVER} --connect {connect} {flags}".rstrip(),
        actions=[*actions, action("agent-reached", ready_text=(AGENT_REACHED,))],
        expected_text=(f"Question: {TEAM_SERVER_TEXT}", AGENT_REACHED),
        captures=(*captures, "agent-reached"),
        required="agent-reached",
        instructions=instructions,
        outcome=outcome,
    )


__all__ = [
    "ADMISSION_TEXT",
    "AGENT_DRIVER",
    "AGENT_REACHED",
    "APPROVAL_TEXT",
    "COMPANY",
    "COMPANY_STEP",
    "INVITE_STEP",
    "LOCAL_HOME",
    "LOCAL_NOTICE",
    "MATCH_CODE_LABEL",
    "OWNER_HOME",
    "OWNER_STEP",
    "SERVER",
    "TEAM_SERVER_TEXT",
    "WIZARD_CHROME_TEXT",
    "admission_case",
    "agent_case",
    "agent_gate",
    "wizard_browser_approval",
    "wizard_case",
    "wizard_code_wait",
    "wizard_start",
]
