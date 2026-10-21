"""The installer campaign's machine admission journeys."""

from __future__ import annotations

import inspect
import re

from runtime.api.domain.test_qa_release_channel_target import _target
from yoke_cli.config import (
    onboard_wizard_flow_machine_admission,
    onboard_wizard_flow_team_server,
    onboard_wizard_hosted_machine_views,
)
from yoke_cli.config.local_reachability import LOCAL_REACHABILITY_NOTICE
from yoke_core.domain.installer_campaign_mission_cases import (
    INSTALLER_CAMPAIGN_CASES,
)
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)
from yoke_core.domain.installer_campaign_machine_admission_recipes import (
    ADMISSION_TEXT,
    APPROVAL_TEXT,
    LOCAL_NOTICE,
    TEAM_SERVER_TEXT,
)
from yoke_core.domain.installer_campaign_regression_cases import recovery_cases
from yoke_core.domain.machine_qa_admission_gate import INVITE_PROMPT
from yoke_core.domain.machine_qa_fixture_validation import (
    validate_post_state_assertions,
    validate_setup_operations,
)
from yoke_core.domain.machine_qa_method_contracts import (
    validate_machine_method_config,
)

KEYS = (
    "own-machine-human",
    "own-machine-agent",
    "teammate-invite-human",
    "teammate-invite-agent",
    "company-sign-in-human",
    "company-sign-in-agent",
    "local-refusal-human",
    "local-refusal-agent",
)
PROOF = {
    "own-machine": ("self-hosted", "owner-admitted", "admission_owner_approval"),
    "teammate-invite": ("self-hosted", "teammate-admitted", "admission_invite_entry"),
    "company-sign-in": (
        "self-hosted-company-sign-in",
        "teammate-admitted",
        "machine_browser_approval",
    ),
    "local-refusal": ("local", "nothing-admitted", None),
}


def _cases() -> list[dict]:
    return installer_campaign_cases_for_target(
        _target("prod"), primary_machine="primary", joining_machine="joining"
    )


def _admission() -> list[dict]:
    return [case for case in _cases() if case["case_key"] in KEYS]


def test_eight_journeys_follow_the_original_cases_unchanged() -> None:
    cases = _cases()
    original = [case["case_key"] for case in INSTALLER_CAMPAIGN_CASES]
    original += [
        case["case_key"]
        for case in recovery_cases(primary_machine="primary", joining_machine="joining")
    ]
    assert [case["case_key"] for case in cases] == [*original, *KEYS]
    assert [case["position"] for case in cases[-8:]] == list(range(len(cases) - 7, len(cases) + 1))
    assert all(case["method_config"]["machine"] == "primary" for case in cases[-8:])


def test_each_journey_validates_and_proves_the_servers_real_rows() -> None:
    for case in _admission():
        mode, expect, _purpose = PROOF[case["case_key"].rsplit("-", 1)[0]]
        config = validate_machine_method_config(
            case["method_id"],
            case["method_config"],
            entry_surface=case["entry_surface"],
            required_completion=case["required_completion"],
            host_baseline="fresh-host",
        )
        setup = validate_setup_operations(config["setup_operations"])
        assert ("fixture.machine-admission-prepare", {"mode": mode}) in setup
        assert validate_post_state_assertions(config["post_state_assertions"]) == (
            (
                "fixture.machine-admission-state-assert",
                {"mode": mode, "expect": expect},
            ),
        )


def test_the_run_does_every_step_and_no_person_gate_remains() -> None:
    for case in _admission():
        _mode, _expect, gate = PROOF[case["case_key"].rsplit("-", 1)[0]]
        actions = case["method_config"]["actions"]
        gates = [row for row in actions if row.get("operator_gate")]
        assert [row["operator_gate"] for row in gates] == ([gate] if gate else [])
        assert not any("human_purpose" in row for row in gates)
        assert all(row.get("keys", []) in ([], ["Enter"]) for row in gates)
        assert "invite_code=" not in case["entry_surface"]
        assert "--token" not in case["entry_surface"]
        assert "human gate" not in case["instructions"]
    company_agent = next(
        case for case in _admission() if case["case_key"] == "company-sign-in-agent"
    )
    assert "--open-link" in company_agent["entry_surface"]


def test_journeys_wait_for_the_screens_setup_actually_shows() -> None:
    team_server = inspect.getsource(onboard_wizard_flow_team_server)
    admission = inspect.getsource(onboard_wizard_flow_machine_admission)
    approval = inspect.getsource(onboard_wizard_hosted_machine_views)
    assert TEAM_SERVER_TEXT in team_server
    assert '"connect.team_server_url"' in team_server
    assert ADMISSION_TEXT in admission
    assert all(
        f'SelectionRow(\n                        "{value}",' in admission
        for value in ("own", "invite")
    )
    assert f'"connect.invite_code",\n            STEP_CONNECT,\n            "{INVITE_PROMPT}",' in admission
    # A prompt's guidance is never drawn, so no journey may wait for it.
    guidance = re.findall(
        r'guidance="([^"]+)"', "\n".join((team_server, admission, approval))
    )
    for case in _admission():
        for action in case["method_config"]["actions"]:
            for marker in action.get("ready_text", ()):
                assert not any(marker in text for text in guidance), marker
    assert APPROVAL_TEXT[0] in approval
    assert LOCAL_REACHABILITY_NOTICE.startswith(LOCAL_NOTICE)
