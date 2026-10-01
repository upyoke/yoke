"""Mission starting state validates package names and survives materialization."""

import pytest

from yoke_core.domain.qa_method_config_validation import (
    validate_method_config,
    QaMethodConfigError,
)


def test_mission_accepts_declared_package_state():
    config = validate_method_config(
        "agent-mission",
        {
            "executor": "informed_subagent",
            "machine": "linux-lab",
            "host_starting_state": {"os_packages": {"absent": ["python3.12-venv"]}},
        },
    )
    assert config["host_starting_state"]["os_packages"] == {
        "absent": ["python3.12-venv"],
        "present": [],
    }


@pytest.mark.parametrize(
    "packages",
    [
        {"absent": ["python3; touch /tmp/unsafe"]},
        {"absent": ["--force-yes"]},
        {"absent": ["python3-minimal"]},
        {"absent": ["python3-venv"], "present": ["python3-venv"]},
        {"command": "sudo remove stuff"},
    ],
)
def test_unsafe_or_conflicting_fixture_is_refused(packages):
    with pytest.raises(QaMethodConfigError):
        validate_method_config(
            "agent-mission",
            {
                "executor": "informed_subagent",
                "host_starting_state": {"os_packages": packages},
            },
        )


def test_host_wait_cli_is_separate_from_verdicts():
    from yoke_core.domain.qa_plan_review_cli import _submission

    assert (
        _submission('{"host_wait":{"machine":"linux-lab","rationale":"lease 1"}}')[
            "host_wait"
        ]["machine"]
        == "linux-lab"
    )
    with pytest.raises(ValueError, match="without verdicts"):
        _submission('{"host_wait":{},"verdicts":[]}')
