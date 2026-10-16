"""State assertions consume the journey that actually produced their state."""

import os
import shutil
import subprocess
import sys

import pytest

from yoke_cli.config.onboard_plan_labels import friendly_line
from runtime.api.domain.test_qa_release_channel_target import _target
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)


def _cases():
    return installer_campaign_cases_for_target(
        _target("prod"), primary_machine="primary", joining_machine="joining"
    )


def test_state_checks_directly_follow_their_real_state_producers():
    cases = _cases()
    keys = [case["case_key"] for case in cases]
    for producer, consumer in (
        ("cold-start-hosted", "token-perms"),
        ("apply-handoff", "universe-born"),
    ):
        assert keys[keys.index(producer) + 1] == consumer
        assert cases[keys.index(consumer)]["starting_state"] == "inherit"
    assert [case["position"] for case in cases] == list(range(1, len(cases) + 1))


@pytest.mark.skipif(shutil.which("zsh") is None, reason="requires zsh")
@pytest.mark.parametrize(
    "directory_mode,file_mode",
    [(0o700, 0o600), (0o755, 0o600), (0o700, 0o644), (0o700, None)],
)
def test_named_token_checks_distinguish_absence_and_permission_failures(
    tmp_path, directory_mode, file_mode
):
    secrets = tmp_path / ".yoke" / "secrets"
    secrets.mkdir(parents=True, mode=directory_mode)
    if file_mode is not None:
        token = secrets / "fixture.token"
        token.touch(mode=file_mode)
    case = next(case for case in _cases() if case["case_key"] == "token-perms")
    outcomes = []
    for assertion in case["method_config"]["assertions"]:
        script = assertion["argv"][2].replace("$HOME", "$fixture_home")
        if sys.platform != "darwin":
            script = script.replace("/usr/bin/stat -f '%Lp'", "/usr/bin/stat -c '%a'")
        result = subprocess.run(
            ["zsh", "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "fixture_home": str(tmp_path)},
        )
        outcomes.append(result.returncode == 0)
        assert result.stdout.strip() in {
            "token-file-exists",
            "secrets-directory-mode-700",
            "token-file-modes-600",
        }
    assert outcomes == [
        file_mode is not None,
        directory_mode == 0o700,
        file_mode == 0o600,
    ]


def test_review_captures_the_write_names_and_backs_out_without_apply():
    case = next(case for case in _cases() if case["case_key"] == "review-frame")
    actions = case["method_config"]["actions"]
    assert actions[-3]["keys"] == ["Down", "Enter"]
    assert actions[-3]["ready_text"] == ["Show all changes"]
    assert actions[-2]["step"] == "pending-write-list"
    reuse_line = friendly_line("reuse-session-relay-token", "")
    assert reuse_line in actions[-2]["ready_text"]
    assert reuse_line in case["method_config"]["expected_text"]
    assert friendly_line("store-token-reference", "") not in actions[-2]["ready_text"]
    assert actions[-1]["keys"] == ["Escape"]
    assert "pending-write-list" in case["method_config"]["capture_checkpoints"]
    assert case["required_completion"] == "back-before-apply"
    assert all(action["step"] != "apply" for action in actions)
