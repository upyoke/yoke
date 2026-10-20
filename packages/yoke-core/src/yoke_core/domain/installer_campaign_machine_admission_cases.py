"""Installer campaign journeys that admit a machine or refuse admission locally.

Each journey runs twice: in the full-screen wizard, and in agent mode played
by ``machine_qa_setup_agent_driver``. Every case installs the candidate,
starts that candidate's own disposable server or local universe
(``fixture.machine-admission-prepare``), performs the owner's or teammate's
step itself through a typed gate (no step waits on a person), and finally
proves the universe's real rows (``fixture.machine-admission-state-assert``).
"""

from __future__ import annotations

from yoke_core.domain.installer_campaign_machine_admission_recipes import (
    ADMISSION_TEXT,
    AGENT_REACHED,
    COMPANY,
    COMPANY_STEP,
    INVITE_STEP,
    LOCAL_HOME,
    LOCAL_NOTICE,
    MATCH_CODE_LABEL,
    OWNER_STEP,
    SERVER,
    TEAM_SERVER_TEXT,
    admission_case,
    agent_case,
    agent_gate,
    wizard_browser_approval,
    wizard_case,
    wizard_code_wait,
    wizard_start,
)
from yoke_core.domain.machine_qa_operator_gate_contract import (
    ADMISSION_INVITE_ENTRY,
    ADMISSION_OWNER_APPROVAL,
    MACHINE_BROWSER_APPROVAL,
)
from yoke_core.domain.machine_qa_fixture_constants import YOKE_BIN
from yoke_core.domain.installer_campaign_plan_common import (
    CHOOSE_BACKLOG_KEYS,
    MACHINE_GITHUB_TEXT,
    action,
    transition,
)

_URL_ANSWER = f"connect.team_server_url={SERVER}"

OWN_MACHINE_HUMAN = wizard_case(
    "own-machine-human",
    mode="self-hosted",
    expect="owner-admitted",
    actions=[
        *wizard_start(),
        action("machine-admission", ready_text=(ADMISSION_TEXT,)),
        transition("own-machine", "Enter", ready_text=("This is my own machine",)),
        *wizard_code_wait("owner-approves"),
    ],
    captures=("machine-admission", "match-code", "machine-github"),
    instructions="In the wizard choose This is my own machine; at the match code "
    + OWNER_STEP,
    outcome="The new machine connects as the owner after the owner's approval; the server "
    "holds one new machine and credential for the owner and no new person.",
)
OWN_MACHINE_AGENT = agent_case(
    "own-machine-agent",
    mode="self-hosted",
    expect="owner-admitted",
    answers=(_URL_ANSWER, "connect.machine_admission=own"),
    actions=[
        action(
            "match-code",
            ready_text=(MATCH_CODE_LABEL, "Open:"),
            ready_timeout_seconds=180,
        ),
        agent_gate("owner-approves", ADMISSION_OWNER_APPROVAL, AGENT_REACHED),
    ],
    captures=("match-code",),
    instructions="The scripted agent chooses this is my own machine and shows the match "
    "code; " + OWNER_STEP,
    outcome="Each agent setup call ends at the browser step; after the owner's approval the "
    "next call reaches Connect GitHub as the owner; the server holds one new machine for "
    "the owner.",
)
TEAMMATE_INVITE_HUMAN = wizard_case(
    "teammate-invite-human",
    mode="self-hosted",
    expect="teammate-admitted",
    actions=[
        *wizard_start(),
        action("machine-admission", ready_text=(ADMISSION_TEXT,)),
        transition(
            "enter-invite", *CHOOSE_BACKLOG_KEYS, ready_text=("Enter invite code",)
        ),
        action(
            "invite-code", ready_text=("Enter invite code.", "The invite is a secret.")
        ),
        agent_gate(
            "teammate-enters-invite", ADMISSION_INVITE_ENTRY, MACHINE_GITHUB_TEXT[0]
        ),
        action("machine-github"),
    ],
    captures=("machine-admission", "invite-code", "machine-github"),
    instructions="In the wizard choose Enter invite code; " + INVITE_STEP,
    outcome="The invited teammate's machine connects once as the teammate; the invite is "
    "consumed by that machine and the teammate holds an org role.",
)
TEAMMATE_INVITE_AGENT = agent_case(
    "teammate-invite-agent",
    mode="self-hosted",
    expect="teammate-admitted",
    answers=(_URL_ANSWER, "connect.machine_admission=invite"),
    actions=[
        action(
            "invite-handoff",
            ready_text=(
                "Question: Enter invite code.",
                "Handing this step to the person",
            ),
        ),
        transition("handoff-url", "Enter", ready_text=(TEAM_SERVER_TEXT,)),
        action("handoff-admission", ready_text=(ADMISSION_TEXT,)),
        transition(
            "handoff-invite", *CHOOSE_BACKLOG_KEYS, ready_text=("Enter invite code",)
        ),
        action(
            "handoff-invite-code",
            ready_text=("Enter invite code.", "The invite is a secret."),
        ),
        agent_gate(
            "teammate-redeems-privately", ADMISSION_INVITE_ENTRY, MACHINE_GITHUB_TEXT[0]
        ),
        transition("leave-wizard", "C-c", ready_text=(MACHINE_GITHUB_TEXT[0],)),
    ],
    captures=("invite-handoff", "handoff-invite-code"),
    instructions="The scripted agent stops at the secret invite question and opens the "
    "wizard; the run presses Enter for the URL, chooses Enter invite code, then "
    + INVITE_STEP
    + " Once connected it presses Ctrl-C so the agent resumes.",
    outcome="Agent setup never receives the invite, resumes after the private wizard step "
    "and reaches Connect GitHub as the teammate; the invite is consumed once.",
)
COMPANY_SIGN_IN_HUMAN = wizard_case(
    "company-sign-in-human",
    mode="self-hosted-company-sign-in",
    expect="teammate-admitted",
    actions=[
        *wizard_start(),
        *wizard_browser_approval("teammate-signs-in"),
    ],
    captures=("match-code", "machine-github"),
    instructions="The wizard finds company sign-in and opens the approval link; "
    + COMPANY_STEP,
    outcome="The teammate's own company sign-in admits the machine to the teammate, not the "
    "owner; the company identity links to the teammate, who holds an org role.",
)
COMPANY_SIGN_IN_AGENT = agent_case(
    "company-sign-in-agent",
    mode="self-hosted-company-sign-in",
    expect="teammate-admitted",
    answers=(f"connect.team_server_url={COMPANY}",),
    actions=[
        action(
            "match-code",
            ready_text=(MATCH_CODE_LABEL, "Open:"),
            ready_timeout_seconds=180,
        ),
        agent_gate("teammate-signs-in", MACHINE_BROWSER_APPROVAL, AGENT_REACHED),
    ],
    captures=("match-code",),
    instructions="The scripted agent shows the approval link and match code and opens "
    "the link; " + COMPANY_STEP,
    outcome="Each agent setup call ends at the browser step; after the teammate's company "
    "sign-in the next call reaches Connect GitHub as the teammate, linked to the company "
    "identity.",
)
LOCAL_REFUSAL_HUMAN = admission_case(
    "local-refusal-human",
    mode="local",
    expect="nothing-admitted",
    entry=(
        f"export YOKE_MACHINE_HOME={LOCAL_HOME}; {YOKE_BIN} setup --tui --connect "
        f"{SERVER}; {YOKE_BIN} invite 'Fixture Teammate'; {YOKE_BIN} machines pending; "
        "printf '%s\\n' local-refusal-human"
    ),
    actions=[
        action(
            "local-notice",
            ready_text=(TEAM_SERVER_TEXT, LOCAL_NOTICE),
            ready_timeout_seconds=180,
        ),
        transition("leave-setup", "C-c", ready_text=(LOCAL_NOTICE,)),
        action(
            "local-refusal",
            ready_text=("error (invite_local_universe)", "local-refusal-human"),
        ),
    ],
    expected_text=(
        LOCAL_NOTICE,
        "error (invite_local_universe)",
        "local-refusal-human",
    ),
    captures=("local-notice", "local-refusal"),
    required="local-refusal",
    instructions="On a local universe the wizard explains that teammates cannot join; "
    "inviting and listing waiting machines refuse with the same recovery.",
    outcome="Setup, yoke invite and yoke machines pending all show Reachable here only and "
    "point to yoke self-host init; no person, machine or credential is created.",
)
LOCAL_REFUSAL_AGENT = admission_case(
    "local-refusal-agent",
    mode="local",
    expect="nothing-admitted",
    entry=(
        f"export YOKE_MACHINE_HOME={LOCAL_HOME}; {YOKE_BIN} setup --agent --connect "
        f"{SERVER}; {YOKE_BIN} invite 'Fixture Teammate' --json; "
        f"{YOKE_BIN} machines pending --json; {YOKE_BIN} setup --agent --discard; "
        "printf '%s\\n' local-refusal-agent"
    ),
    actions=[action("local-refusal-agent", ready_text=("local-refusal-agent",))],
    expected_text=(LOCAL_NOTICE, '"code": "invite_local_universe"', '"mode": "local"'),
    captures=(),
    required="local-refusal-agent",
    instructions="An agent on a local universe reads the team-server question, an invite "
    "and the waiting-machine list as JSON; each names the local refusal.",
    outcome="The agent question shows Reachable here only, yoke invite --json refuses "
    "invite_local_universe, machines pending reports mode local; nothing is admitted.",
    execution_mode="ssh-command",
)

MACHINE_ADMISSION_CASES = tuple(
    {**case, "position": position}
    for position, case in enumerate(
        (
            OWN_MACHINE_HUMAN,
            OWN_MACHINE_AGENT,
            TEAMMATE_INVITE_HUMAN,
            TEAMMATE_INVITE_AGENT,
            COMPANY_SIGN_IN_HUMAN,
            COMPANY_SIGN_IN_AGENT,
            LOCAL_REFUSAL_HUMAN,
            LOCAL_REFUSAL_AGENT,
        ),
        30,
    )
)

__all__ = ["MACHINE_ADMISSION_CASES"]
