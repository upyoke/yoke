"""Validation boundaries for registered Machine QA fixture operations."""

from __future__ import annotations

import pytest

from runtime.api.domain.machine_qa_fixture_test_support import (
    FakeRemote,
    fixture_executor as _executor,
    operation as _operation,
)
from yoke_cli.config import path_doctor
from yoke_core.domain.machine_qa_fixture_constants import (
    CAMPAIGN_WORKSPACE_PATHS,
    FAKE_TOKEN_PATH,
)
from yoke_core.domain.machine_qa_fixture_operations import (
    MachineQaFixtureOperationError,
    MachineQaFixtureOperationExecutor,
)
from yoke_core.domain.machine_qa_fixture_validation import (
    POST_VALIDATORS,
    SETUP_VALIDATORS,
)
from yoke_core.domain.machine_qa_recipe_contracts import (
    REGISTERED_POST_STATE_ASSERTION_IDS,
    REGISTERED_SETUP_OPERATION_IDS,
)


def test_operation_registry_has_validation_and_execution_coverage() -> None:
    executor = _executor(FakeRemote())

    assert frozenset(SETUP_VALIDATORS) == REGISTERED_SETUP_OPERATION_IDS
    assert frozenset(POST_VALIDATORS) == REGISTERED_POST_STATE_ASSERTION_IDS
    assert frozenset(executor._setup_handlers()) == REGISTERED_SETUP_OPERATION_IDS
    assert frozenset(executor._post_handlers()) == REGISTERED_POST_STATE_ASSERTION_IDS


def test_workspace_reset_stays_inside_executor_owned_paths() -> None:
    executor = _executor(FakeRemote())
    result = executor.execute_setup_operations(
        [
            _operation(
                "installer-campaign.workspace-reset",
                paths=list(CAMPAIGN_WORKSPACE_PATHS),
            )
        ]
    )

    assert result.ok
    assert executor.close().ok


def test_fixture_executor_rejects_launcher_outside_bounded_home() -> None:
    remote = FakeRemote()
    path_state = path_doctor.resolve_path_state_contract(
        env={
            "HOME": "/Users/tester",
            "SHELL": "/bin/zsh",
            "XDG_BIN_HOME": "/opt/yoke/bin",
        }
    )

    with pytest.raises(
        MachineQaFixtureOperationError,
        match="launcher escapes",
    ):
        MachineQaFixtureOperationExecutor(
            run_remote=remote.run,
            upload_text=remote.upload,
            home="/Users/tester",
            path_state=path_state,
        )

    assert remote.commands == []
    assert remote.uploads == {}


@pytest.mark.parametrize(
    "operation",
    [
        _operation("fixture.shell-run", script="rm -rf /"),
        _operation(
            "installer-campaign.workspace-reset",
            paths=["/tmp/not-campaign-owned"],
        ),
        _operation(
            "installer.product-state-reset",
            paths=["~/.local"],
        ),
        _operation(
            "fixture.yoke-api-start",
            bind_host="127.0.0.1",
            port=19087,
            profile="identity-success",
            token_path=FAKE_TOKEN_PATH,
            function_errors={"projects.get": {"message": "injected"}},
        ),
    ],
)
def test_validation_refuses_unregistered_code_and_destructive_targets(
    operation,
) -> None:
    remote = FakeRemote()
    executor = _executor(remote)
    with pytest.raises(MachineQaFixtureOperationError):
        executor.execute_setup_operations([operation])
    assert remote.commands == []
    assert remote.uploads == {}


def test_whole_batch_is_validated_before_the_first_mutation() -> None:
    remote = FakeRemote()
    executor = _executor(remote)
    valid = _operation(
        "installer-campaign.workspace-reset",
        paths=list(CAMPAIGN_WORKSPACE_PATHS),
    )
    invalid = _operation("fixture.unknown")
    with pytest.raises(MachineQaFixtureOperationError):
        executor.execute_setup_operations([valid, invalid])
    assert remote.commands == []


def test_current_release_accepts_environment_bound_distribution_values() -> None:
    remote = FakeRemote()
    executor = _executor(remote)

    result = executor.execute_setup_operations(
        [
            _operation(
                "installer.current-release-prepare",
                base_url="https://downloads.example.net/yoke",
                channel="customer-canary.7",
                evidence_name="external-release",
                no_onboard=True,
                remove_existing_launcher=True,
            )
        ]
    )

    assert result.ok


@pytest.mark.parametrize(
    ("base_url", "channel"),
    [
        ("file:///tmp/yoke", "stable"),
        ("https://user@example.net/yoke", "stable"),
        ("https://example.net/yoke?token=secret", "stable"),
        ("https://example.net/yoke", "bad channel"),
    ],
)
def test_current_release_rejects_unsafe_distribution_values(
    base_url: str,
    channel: str,
) -> None:
    executor = _executor(FakeRemote())

    with pytest.raises(MachineQaFixtureOperationError):
        executor.execute_setup_operations(
            [
                _operation(
                    "installer.current-release-prepare",
                    base_url=base_url,
                    channel=channel,
                    evidence_name="invalid-release",
                    no_onboard=True,
                    remove_existing_launcher=True,
                )
            ]
        )
