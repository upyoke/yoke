"""Closed-registry coverage for Machine QA fixture operations."""

from __future__ import annotations

import json

from runtime.api.domain.machine_qa_fixture_test_support import (
    FakeRemote,
    fixture_executor as _executor,
    operation as _operation,
)
from yoke_core.domain.machine_qa_fixture_constants import (
    FAKE_TOKEN_PATH,
    MANAGED_BLOCK_MARKER,
    PATH_IDEMPOTENCE_STARTUP_FILES,
    YOKE_BIN,
)


def test_fake_service_uses_a_closed_profile_and_idempotent_cleanup() -> None:
    remote = FakeRemote()
    executor = _executor(remote)
    result = executor.execute_setup_operations(
        [
            _operation(
                "fixture.yoke-api-start",
                bind_host="127.0.0.1",
                port=19087,
                profile="identity-success",
                token_path=FAKE_TOKEN_PATH,
            )
        ]
    )
    assert result.ok
    assert result.evidence == {
        "operations": [{"id": "fixture.yoke-api-start", "outcome": "passed"}]
    }
    profile_text = next(
        content
        for path, content in remote.uploads.items()
        if path.endswith("19087-identity-success.json")
    )
    profile = json.loads(profile_text)
    assert profile["actor"]["label"] == "recipe actor"
    assert "function_errors" not in profile
    commands = [command for command, _timeout in remote.commands]
    assert all("python3" not in command for command in commands)
    assert any(
        command.startswith("/bin/zsh -fc ")
        and executor.path_state.yoke_bin in command
        and "service_manager.py start" in command
        for command in commands
    )

    first_close = executor.close()
    assert first_close.ok
    command_count = len(remote.commands)
    upload_count = len(remote.uploads)
    assert executor.close().ok
    assert len(remote.commands) == command_count
    assert len(remote.uploads) == upload_count


def test_cleanup_failure_remains_retryable_without_restarting_service() -> None:
    remote = FakeRemote()
    executor = _executor(remote)
    assert executor.execute_setup_operations(
        [
            _operation(
                "fixture.yoke-api-start",
                bind_host="127.0.0.1",
                port=19088,
                profile="identity-no-access",
                token_path=FAKE_TOKEN_PATH,
            )
        ]
    ).ok
    remote.fail_once_contains = "service_manager.py stop"
    first = executor.close()
    assert not first.ok
    assert first.error_code == "fixture_cleanup_failed"
    second = executor.close()
    assert second.ok
    count = len(remote.commands)
    assert executor.close().ok
    assert len(remote.commands) == count


def test_temporary_invalid_token_is_restored_and_never_enters_evidence() -> None:
    remote = FakeRemote()
    stored = "/Users/tester/.yoke/secrets/stage.token"
    remote.existing.add(stored)
    executor = _executor(remote)
    result = executor.execute_setup_operations(
        [
            _operation(
                "machine.token-file-prepare",
                path="~/.yoke/secrets/stage.token",
                state="synthetic-invalid",
                restore_after=True,
            )
        ]
    )
    assert result.ok
    serialized_evidence = json.dumps(result.evidence)
    invalid_value = "not-a-real-yoke-token"
    assert invalid_value not in serialized_evidence
    assert all(invalid_value not in command for command, _timeout in remote.commands)
    assert any(invalid_value in content for content in remote.uploads.values())
    closed = executor.close()
    assert closed.ok
    assert closed.evidence == {
        "operations": [{"id": "machine.token-file-prepare", "outcome": "passed"}]
    }


def test_auth_clear_restores_opaque_config_and_secret_tree_after_retry() -> None:
    remote = FakeRemote()
    config_path = "/Users/tester/.yoke/config.json"
    secrets_path = "/Users/tester/.yoke/secrets"
    stage_path = f"{secrets_path}/stage.token"
    prod_path = f"{secrets_path}/prod.token"
    originals = {
        config_path: "private-config-value",
        stage_path: "private-stage-value",
        prod_path: "private-prod-value",
    }
    remote.directories.update({"/Users/tester/.yoke", secrets_path})
    remote.existing.update(originals)
    remote.contents.update(originals)
    executor = _executor(remote)

    setup = executor.execute_setup_operations([_operation("machine.yoke-auth-clear")])
    assert setup.ok
    assert not remote.existing.intersection(originals)

    remote.fail_once_contains = "auth-0/config.json /Users/tester/.yoke/config.json"
    first_close = executor.close()
    assert not first_close.ok
    assert first_close.evidence == {
        "operations": [{"id": "machine.yoke-auth-clear", "outcome": "failed"}]
    }
    second_close = executor.close()
    assert second_close.ok
    assert second_close.evidence == {
        "operations": [{"id": "machine.yoke-auth-clear", "outcome": "passed"}]
    }
    assert secrets_path in remote.directories
    assert {path: remote.contents[path] for path in originals} == originals
    serialized_evidence = json.dumps(
        [setup.evidence, first_close.evidence, second_close.evidence]
    )
    for secret_value in originals.values():
        assert secret_value not in serialized_evidence
        assert all(secret_value not in command for command, _timeout in remote.commands)
    command_text = "\n".join(command for command, _timeout in remote.commands)
    uv_path = executor.path_state.tool_paths[executor.path_state.tools.index("uv")]
    for campaign_reset_target in (
        "/Users/tester/code",
        uv_path,
        "/Users/tester/yoke-smoke-tokens",
        executor.path_state.supported_startup_files[0],
        "YOKE_MAC_WIPE_OK",
    ):
        assert campaign_reset_target not in command_text


def test_post_state_assertion_discards_remote_output_from_evidence() -> None:
    remote = FakeRemote()
    executor = _executor(remote)
    result = executor.execute_post_state_assertions(
        [
            _operation(
                "source-dev.checkout-state-assert",
                checkout_path="/tmp/yoke-project-source-dev-fresh",
                apply_report_path="/tmp/yoke-source-dev-post-apply.json",
                expected_origin="https://github.com/upyoke/yoke.git",
                expected_branch="main",
                require_git_history=True,
                require_source_links=True,
                require_git_hooks=True,
                forbid_product_copy_directories=True,
            )
        ]
    )
    assert result.ok
    assert remote.stdout not in json.dumps(result.evidence)
    assert result.evidence == {
        "operations": [
            {
                "id": "source-dev.checkout-state-assert",
                "outcome": "passed",
            }
        ]
    }
    assertion_command = remote.commands[-1][0]
    assert "python3" not in assertion_command
    assert assertion_command.startswith("/bin/zsh -fc ")
    assert executor.path_state.yoke_bin in assertion_command
    assert "source_checkout_assertion.py" in assertion_command


def test_path_rerun_assertion_uses_installed_launcher_interpreter() -> None:
    remote = FakeRemote()
    executor = _executor(remote)

    result = executor.execute_setup_operations(
        [
            _operation(
                "machine.path-idempotence-prepare",
                emit_evidence=True,
                expected_block_count=1,
                managed_block_marker=MANAGED_BLOCK_MARKER,
                repeats=2,
                startup_files=list(PATH_IDEMPOTENCE_STARTUP_FILES),
                yoke_bin=YOKE_BIN,
            )
        ]
    )

    assert result.ok
    commands = [command for command, _timeout in remote.commands]
    assert all("python3" not in command for command in commands)
    assert commands[-1].startswith("/bin/zsh -fc ")
    assert executor.path_state.yoke_bin in commands[-1]
    assert "startup_marker_assertion.py" in commands[-1]


def test_terminal_size_is_deferred_until_a_native_session_exists() -> None:
    remote = FakeRemote()
    executor = _executor(remote)
    result = executor.execute_setup_operations(
        [_operation("terminal.size-prepare", columns=80, rows=24)]
    )

    assert result.ok
    assert result.evidence == {
        "operations": [{"id": "terminal.size-prepare", "outcome": "passed"}]
    }
    assert remote.commands == []
    assert remote.terminal_sizes == [(80, 24)]
