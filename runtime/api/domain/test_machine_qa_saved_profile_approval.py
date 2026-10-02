"""Browser approvals use the candidate profile and fail before unsafe clicks."""

import json
from functools import partial
from types import SimpleNamespace
import subprocess

import pytest

from yoke_contracts.machine_qa_execution import GUI_SESSION_CONTEXT

from yoke_core.domain.machine_qa_saved_profile_approval import (
    approve_machine_from_profile as _approve_machine_from_profile,
)

from runtime.api.domain.machine_qa_browser_flow_test_support import (
    EXAMPLE_FLOW,
    EXAMPLE_ORIGIN,
)

approve_machine_from_profile = partial(_approve_machine_from_profile, flow=EXAMPLE_FLOW)
ORIGIN = EXAMPLE_ORIGIN
URL = ORIGIN + "/connect?user_code=AB12-CD34"


class Control:
    def __init__(
        self, *, expired=False, missing=False, hostile=False, failed=False, os="linux"
    ):
        self.material = SimpleNamespace(
            project="project",
            settings={
                "resource_name": "rig",
                "os": os,
                **(
                    {}
                    if missing
                    else {"browser_profile_baseline_path": "/goldens/browser"}
                ),
            },
        )
        self.path_state = SimpleNamespace(yoke_bin="/test/.local/bin/yoke")
        self.commands = []
        self.timeouts = []
        self.contexts = []
        self.expired, self.hostile, self.failed = expired, hostile, failed

    def run_command(self, argv, **options):
        self.commands.append(argv)
        self.timeouts.append(options["timeout"])
        self.contexts.append(options.get("required_session_context"))
        assert argv[0] == self.path_state.yoke_bin
        if argv[3] == "status":
            data = {"profile": {"status": "not authorized"}}
        elif argv[3] == "setup":
            data = {"ok": True, "profile_restore": {"restored": True}}
        else:
            data = {
                "success": True,
                "data": {
                    "success": not self.failed,
                    "url": "https://foreign.example.test" if self.hostile else URL,
                },
            }
            if self.expired:
                data["data"]["authenticationWall"] = True
        return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")


def test_approval_restores_after_install_and_proves_exact_control():
    control = Control()
    result = approve_machine_from_profile(
        control, verification_url=ORIGIN + "/connect", user_code="AB12-CD34"
    )
    assert result.ok
    setup = control.commands[1]
    assert setup[-2:] == ["--profile-baseline", "/goldens/browser"]
    actions = [json.loads(argv[-1]) for argv in control.commands[2:]]
    assert [step["action"] for step in actions] == ["navigate", "assert", "click"]
    assert actions[0]["route"] == URL
    assert result.evidence["result_url"] == ORIGIN + "/connect"
    assert result.evidence["profile_restored"]


@pytest.mark.parametrize("os", ["linux", "windows", "macos"])
def test_browser_operations_use_the_host_session_gateway(os):
    control = Control(os=os)
    result = approve_machine_from_profile(
        control, verification_url=ORIGIN + "/connect", user_code="AB12-CD34"
    )
    assert result.ok
    expected = GUI_SESSION_CONTEXT if os == "macos" else None
    assert control.contexts == [expected] * 5


@pytest.mark.parametrize(
    "options,reason",
    [
        ({"missing": True}, "browser_profile_sign_in_missing"),
        ({"expired": True}, "browser_profile_sign_in_expired"),
    ],
)
def test_missing_or_expired_sign_in_is_precise_human_handoff(options, reason):
    control = Control(**options)
    result = approve_machine_from_profile(
        control, verification_url=ORIGIN + "/connect", user_code="AB12-CD34"
    )
    assert not result.ok
    assert result.error_code == reason
    assert result.evidence["human_gate"]["site"] == ORIGIN
    assert result.evidence["human_gate"]["machine"] == "rig"
    assert not any('"action": "click"' in argv[-1] for argv in control.commands)


@pytest.mark.parametrize(
    "options,reason",
    [
        ({"hostile": True}, "machine_browser_approval_destination_invalid"),
        ({"failed": True}, "machine_browser_approval_navigate_failed"),
    ],
)
def test_refused_navigation_never_reaches_approval_click(options, reason):
    control = Control(**options)
    result = approve_machine_from_profile(
        control, verification_url=ORIGIN + "/connect", user_code="AB12-CD34"
    )
    assert not result.ok
    assert result.error_code == reason
    assert "human_gate" not in result.evidence
    assert len(control.commands) == 3


@pytest.mark.parametrize(
    "url",
    [
        ORIGIN + "/anything",
        ORIGIN + "/connect?user_code=old",
        "https://user:password@app.example.test/connect",
    ],
)
def test_unrelated_flow_context_is_refused_before_host_access(url):
    control = Control()
    result = approve_machine_from_profile(
        control, verification_url=url, user_code="AB12-CD34"
    )
    assert result.error_code == "machine_browser_context_invalid"
    assert control.commands == []


def test_browser_phases_share_one_total_budget(monkeypatch):
    clock = iter((0, 1, 5, 8, 9, 11))
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_saved_profile_approval.time.monotonic",
        lambda: next(clock),
    )
    control = Control()
    result = approve_machine_from_profile(
        control,
        verification_url=ORIGIN + "/connect",
        user_code="AB12-CD34",
        timeout_seconds=10,
    )
    assert not result.ok
    assert result.error_code == "machine_browser_approval_timed_out"
    assert control.timeouts == [9, 5, 1]
    assert len(control.commands) == 3
