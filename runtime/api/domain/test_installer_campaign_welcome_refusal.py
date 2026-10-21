"""The welcome mission requires the diagnosed refusal, not an arbitrary exit."""

from runtime.api.domain.test_qa_release_channel_target import _target
from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)


def test_welcome_mission_preserves_the_isolated_refusal_proof():
    case = next(
        case for case in installer_campaign_cases_for_target(
            _target("prod"), primary_machine="primary-test", joining_machine="joining-test"
        ) if case["case_key"] == "welcome-frame"
    )
    assert case["method_id"] == "exploratory-mission"
    assert case["starting_state"] == "as_is"
    assert "HOME=/var/empty" in case["entry_surface"]
    assert "XDG_BIN_HOME=/var/empty/.local/bin" in case["entry_surface"]
    assert "PATH=/usr/bin:/bin:/usr/sbin:/sbin" in case["entry_surface"]
    assert "do not change the real home" in case["instructions"]
    assert "unrelated download failure" in case["instructions"]
    for text in (
        "Your operating system for software delivery", "Installing uv",
        "uv installation failed. Install uv manually", "then rerun: curl -fsSL",
        "Exit code 1 is expected only", "manual-install recovery",
    ):
        assert text in case["expected_outcome"]
