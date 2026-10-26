"""A Command case reaching a Test Machine declares the host it queues for."""

from __future__ import annotations

import pytest

from yoke_core.domain.qa_method_config_validation import (
    HOST_COMMAND_NEEDS_MACHINE,
    QaMethodConfigError,
    validate_method_config,
)

HOST_COMMAND = "yoke test-machine exec --project yoke -- uname -a"


def test_a_host_command_without_a_machine_is_refused() -> None:
    with pytest.raises(QaMethodConfigError) as refused:
        validate_method_config("command", {"command": HOST_COMMAND})

    assert str(refused.value) == HOST_COMMAND_NEEDS_MACHINE
    assert "method_config.test_machine" in str(refused.value)


@pytest.mark.parametrize(
    "command",
    [
        "yoke --env prod test-machine verify --project yoke --test-machine windows-lab",
        "cd /tmp && /usr/local/bin/yoke test-machine reset --project yoke",
    ],
)
def test_global_flags_and_compound_lines_still_need_a_machine(command) -> None:
    with pytest.raises(QaMethodConfigError):
        validate_method_config("command", {"command": command})


def test_a_command_merely_naming_test_machine_needs_no_machine() -> None:
    command = "echo yoke test-machine"
    assert validate_method_config("command", {"command": command})["command"] == command


def test_a_host_command_declaring_its_machine_is_accepted() -> None:
    config = validate_method_config(
        "command", {"command": HOST_COMMAND, "test_machine": "linux-lab"}
    )

    assert config["test_machine"] == "linux-lab"


def test_a_command_that_reaches_no_host_needs_no_machine() -> None:
    assert validate_method_config("command", {"command": "true"})["command"] == "true"
