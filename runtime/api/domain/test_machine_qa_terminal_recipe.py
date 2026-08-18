"""SSH-command terminal recipe and staged-file coverage."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from runtime.api.domain.machine_qa_terminal_recipe_test_support import (
    completed,
    recipe,
)
from yoke_core.domain.machine_qa_recipe_contracts import (
    MachineQaRecipeError,
    validate_terminal_recipe,
)
from yoke_core.domain.ssh_mac_terminal_recipe import execute_terminal_recipe


def test_action_wait_seconds_is_optional_and_normalized_only_when_present() -> None:
    default_config = recipe()
    default_actions = default_config["actions"]
    assert isinstance(default_actions, list)
    normalized_default = validate_terminal_recipe(
        default_config,
        required_completion="done",
    )

    assert "wait_seconds" not in normalized_default["actions"][0]

    waited_config = recipe()
    waited_actions = waited_config["actions"]
    assert isinstance(waited_actions, list)
    waited_actions[0]["wait_seconds"] = 12
    normalized_waited = validate_terminal_recipe(
        waited_config,
        required_completion="done",
    )

    assert normalized_waited["actions"][0]["wait_seconds"] == 12.0


def test_action_target_environment_is_generic_and_preserved() -> None:
    config = recipe()
    actions = config["actions"]
    assert isinstance(actions, list)
    actions[0]["target_environment"] = "blue"

    normalized = validate_terminal_recipe(
        config,
        required_completion="done",
    )

    assert normalized["actions"][0]["target_environment"] == "blue"


@pytest.mark.parametrize("target_environment", ("", " " * 3, "x" * 201))
def test_action_target_environment_rejects_invalid_values(
    target_environment: str,
) -> None:
    config = recipe()
    actions = config["actions"]
    assert isinstance(actions, list)
    actions[0]["target_environment"] = target_environment

    with pytest.raises(MachineQaRecipeError, match="target_environment"):
        validate_terminal_recipe(config, required_completion="done")


@pytest.mark.parametrize("wait_seconds", (-1, 301, True, "1"))
def test_action_wait_seconds_rejects_values_outside_numeric_bounds(
    wait_seconds: object,
) -> None:
    config = recipe()
    actions = config["actions"]
    assert isinstance(actions, list)
    actions[0]["wait_seconds"] = wait_seconds

    with pytest.raises(MachineQaRecipeError, match="wait_seconds"):
        validate_terminal_recipe(
            config,
            required_completion="done",
        )


def test_action_readiness_is_normalized_with_its_timeout() -> None:
    config = recipe()
    actions = config["actions"]
    assert isinstance(actions, list)
    actions[0]["ready_text"] = ["Review what Yoke will save.", "Apply"]
    actions[0]["ready_timeout_seconds"] = 45

    normalized = validate_terminal_recipe(
        config,
        required_completion="done",
    )

    assert normalized["actions"][0]["ready_text"] == [
        "Review what Yoke will save.",
        "Apply",
    ]
    assert normalized["actions"][0]["ready_timeout_seconds"] == 45.0


def test_action_readiness_timeout_requires_source_text() -> None:
    config = recipe()
    actions = config["actions"]
    assert isinstance(actions, list)
    actions[0]["ready_timeout_seconds"] = 45

    with pytest.raises(MachineQaRecipeError, match="requires ready_text"):
        validate_terminal_recipe(
            config,
            required_completion="done",
        )


@pytest.mark.parametrize("ready_timeout_seconds", (0, 301, True, "1"))
def test_action_readiness_timeout_rejects_invalid_values(
    ready_timeout_seconds: object,
) -> None:
    config = recipe()
    actions = config["actions"]
    assert isinstance(actions, list)
    actions[0]["ready_text"] = ["ready"]
    actions[0]["ready_timeout_seconds"] = ready_timeout_seconds

    with pytest.raises(MachineQaRecipeError, match="ready_timeout_seconds"):
        validate_terminal_recipe(
            config,
            required_completion="done",
        )


def test_command_recipe_removes_staged_file_after_success(
    tmp_path: Path,
) -> None:
    source = tmp_path / "stage.token"
    source.write_text("token-material")
    commands: list[str] = []
    uploads: list[tuple[str, bytes]] = []

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return completed(
            command,
            stdout="ready" if command == "yoke onboard" else "",
        )

    result = execute_terminal_recipe(
        run,
        upload_bytes=lambda path, content: uploads.append((path, content)) or True,
        entry_surface="yoke onboard",
        required_completion="done",
        config=recipe(
            stage_files=[
                {
                    "source_path": str(source),
                    "remote_path": "/tmp/yoke-stage.token",
                }
            ]
        ),
        evidence_parent=tmp_path / "evidence",
        secret_values=("token-material",),
    )

    assert result.ok is True
    assert result.evidence["staged_file_cleanup"] is True
    assert uploads == [
        ("/tmp/yoke-stage.token", b"token-material"),
    ]
    assert commands[-1] == "rm -f /tmp/yoke-stage.token"


def test_partial_staging_failure_removes_files_already_uploaded(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_text("one")
    second.write_text("two")
    commands: list[str] = []
    uploads: list[str] = []

    def upload(path: str, _content: bytes) -> bool:
        uploads.append(path)
        return len(uploads) == 1

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return completed(command)

    result = execute_terminal_recipe(
        run,
        upload_bytes=upload,
        entry_surface="yoke onboard",
        required_completion="done",
        config=recipe(
            stage_files=[
                {
                    "source_path": str(first),
                    "remote_path": "/tmp/first",
                },
                {
                    "source_path": str(second),
                    "remote_path": "/tmp/second",
                },
            ]
        ),
        evidence_parent=tmp_path / "evidence",
        secret_values=(),
    )

    assert result.ok is False
    assert result.error_code == "terminal_stage_file_failed"
    assert result.evidence["staged_file_cleanup"] is True
    assert commands == ["rm -f /tmp/first"]


def test_staged_file_cleanup_failure_fails_an_otherwise_green_case(
    tmp_path: Path,
) -> None:
    source = tmp_path / "stage.token"
    source.write_text("token-material")

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        if command.startswith("rm -f "):
            return completed(command, returncode=1)
        return completed(command, stdout="ready")

    result = execute_terminal_recipe(
        run,
        upload_bytes=lambda _path, _content: True,
        entry_surface="yoke onboard",
        required_completion="done",
        config=recipe(
            stage_files=[
                {
                    "source_path": str(source),
                    "remote_path": "/tmp/yoke-stage.token",
                }
            ]
        ),
        evidence_parent=tmp_path / "evidence",
        secret_values=("token-material",),
    )

    assert result.ok is False
    assert result.error_code == "terminal_stage_file_cleanup_failed"
    assert result.evidence["staged_file_cleanup"] is False


def test_staged_secret_is_detected_and_redacted_from_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "stage.token"
    source.write_text("stage-token-value\n")

    def run(
        command: str,
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return completed(
            command,
            stdout=(
                "ready credential=stage-token-value"
                if command == "yoke onboard"
                else ""
            ),
        )

    result = execute_terminal_recipe(
        run,
        upload_bytes=lambda _path, _content: True,
        entry_surface="yoke onboard",
        required_completion="done",
        config=recipe(
            stage_files=[
                {
                    "source_path": str(source),
                    "remote_path": "/tmp/yoke-stage.token",
                }
            ]
        ),
        evidence_parent=tmp_path / "evidence",
        secret_values=(),
    )

    assert result.ok is False
    assert result.error_code == "terminal_recipe_assertion_failed"
    assert "stage-token-value" not in str(result.evidence)
    assert "[REDACTED]" in str(result.evidence)
    assert "secret value appeared" in str(result.evidence)
