"""Focused coverage for the registered dedicated Test Mac reset."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest

from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.ssh_mac_full_reset_test_support import FakeResetTransport
from yoke_cli.config import path_doctor
from yoke_core.domain.host_baseline_operations import run_host_baseline
from yoke_core.domain.ssh_mac_full_reset import (
    execute_full_test_mac_reset,
    is_safe_test_mac_home,
)
from yoke_core.domain.ssh_mac_full_reset_contract import (
    FULL_RESET_MARKER,
    FULL_RESET_REMOTE_PATH,
)
from yoke_core.domain.ssh_mac_full_reset_script import FULL_RESET_SCRIPT


@pytest.mark.parametrize(
    "home",
    (
        "",
        "/",
        "~",
        "$HOME",
        "/tmp/tester",
        "/Users/Shared",
        "/Users/tester/..",
        "/Users//tester",
        "/Users/tester/nested",
    ),
)
def test_reset_rejects_any_non_explicit_dedicated_mac_home(home: str) -> None:
    transport = FakeResetTransport("")

    result = execute_full_test_mac_reset(
        run_remote=transport.run,
        upload_text=transport.upload,
        home=home,
    )

    assert not is_safe_test_mac_home(home)
    assert not result.ok
    assert result.error_code == "unsafe_test_mac_home"
    assert result.evidence == {"paths": []}
    assert transport.uploads == {}
    assert transport.commands == []


def test_reset_uploads_mode_0700_and_accepts_only_closed_outcomes() -> None:
    stdout = "\n".join(
        (
            "YOKE_TOKEN_STAGE_RESTORED",
            "YOKE_TOKEN_PROD_ABSENT",
            "YOKE_INSTALLER_EVIDENCE_MOVED",
            FULL_RESET_MARKER,
        )
    )
    transport = FakeResetTransport(stdout)

    result = execute_full_test_mac_reset(
        run_remote=transport.run,
        upload_text=transport.upload,
        home="/Users/tester",
    )

    assert result.ok
    assert transport.uploads == {FULL_RESET_REMOTE_PATH: FULL_RESET_SCRIPT}
    assert [shlex.split(command) for command, _timeout in transport.commands] == [
        ["/bin/rm", "-f", "--", FULL_RESET_REMOTE_PATH],
        ["/bin/chmod", "0700", FULL_RESET_REMOTE_PATH],
        [FULL_RESET_REMOTE_PATH, "/Users/tester"],
        ["/bin/rm", "-f", "--", FULL_RESET_REMOTE_PATH],
    ]
    assert transport.commands[2][1] == 300
    assert set(result.evidence) == {"paths", "path_state"}
    assert all(set(row) == {"path", "outcome"} for row in result.evidence["paths"])
    rows = {row["path"]: row["outcome"] for row in result.evidence["paths"]}
    assert rows["/tmp/yoke-stage.token"] == "restored-mode-0600"
    assert rows["/tmp/yoke-prod.token"] == "absent"
    assert rows["/Users/tester/.yoke"] == "removed"
    assert rows["/Users/tester/.yoke/installer-smoke-evidence"] == "moved"
    assert rows["/Users/tester/yoke-smoke-evidence"] == "preserved"
    assert rows[str(path_doctor.tool_bin_dir({"HOME": "/Users/tester"}))] == (
        "absent-from-login-and-ssh-path"
    )
    tool_dir = path_doctor.tool_bin_dir({"HOME": "/Users/tester"})
    assert result.evidence["path_state"] == {
        "launcher": str(Path(tool_dir) / "yoke"),
        "launcher_present": False,
        "tool_bin_dir": tool_dir,
        "login_path_present": False,
        "ssh_path_present": False,
    }
    assert "token-bytes" not in repr(result.evidence)


def test_reset_fails_closed_on_extra_output_and_always_cleans_script() -> None:
    transport = FakeResetTransport(
        "\n".join(
            (
                "YOKE_TOKEN_STAGE_ABSENT",
                "YOKE_TOKEN_PROD_ABSENT",
                "YOKE_INSTALLER_EVIDENCE_ABSENT",
                FULL_RESET_MARKER,
                "unexpected-output",
            )
        )
    )

    result = execute_full_test_mac_reset(
        run_remote=transport.run,
        upload_text=transport.upload,
        home="/Users/tester",
    )

    assert not result.ok
    assert result.error_code == "test_mac_reset_output_invalid"
    assert shlex.split(transport.commands[-1][0]) == [
        "/bin/rm",
        "-f",
        "--",
        FULL_RESET_REMOTE_PATH,
    ]
    assert result.evidence == {
        "paths": [
            {"path": "/Users/tester", "outcome": "reset-failed"},
            {"path": FULL_RESET_REMOTE_PATH, "outcome": "removed"},
        ]
    }


def test_existing_retained_evidence_is_reported_without_claiming_a_new_move() -> None:
    transport = FakeResetTransport(
        "\n".join(
            (
                "YOKE_TOKEN_STAGE_ABSENT",
                "YOKE_TOKEN_PROD_ABSENT",
                "YOKE_INSTALLER_EVIDENCE_RETAINED",
                FULL_RESET_MARKER,
            )
        )
    )

    result = execute_full_test_mac_reset(
        run_remote=transport.run,
        upload_text=transport.upload,
        home="/Users/tester",
    )

    assert result.ok
    rows = {row["path"]: row["outcome"] for row in result.evidence["paths"]}
    assert rows["/Users/tester/.yoke/installer-smoke-evidence"] == "absent"
    assert rows["/Users/tester/yoke-smoke-evidence"] == "preserved"


def test_fake_full_reset_preserves_tokens_evidence_ssh_and_clt() -> None:
    control = FakeHostControl()
    token_bytes = dict(control.token_files)

    result = run_host_baseline(control, "fresh-host")

    assert result.ok
    assert control.full_reset_calls == 1
    assert control.token_files == token_bytes
    assert set(control.token_backups.values()) == set(token_bytes.values())
    assert not any(
        path == "/Users/tester/.yoke" or path.startswith("/Users/tester/.yoke/")
        for path in control.existing_paths
    )
    assert (
        "/Users/tester/yoke-smoke-evidence/reset.fake/"
        "installer-smoke-evidence/campaign/report.json" in control.existing_paths
    )
    assert "/Users/tester/.ssh/authorized_keys" in control.existing_paths
    assert "/Library/Developer/CommandLineTools/usr/bin/git" in control.existing_paths
    assert not any(
        path.startswith("/Users/tester/code/") for path in control.existing_paths
    )
    path_state = path_doctor.resolve_path_state_contract(
        env={"HOME": control.home, "SHELL": control.shell}
    )
    tool_bin_suffix = str(Path(path_state.tool_bin_dir).relative_to(control.home))
    assert tool_bin_suffix not in control.files[path_state.startup_file]


def test_full_reset_baseline_converts_adapter_exception_to_closed_failure() -> None:
    control = FakeHostControl()

    def fail_reset():
        raise RuntimeError("untrusted remote detail")

    control.reset_installer_test_host = fail_reset

    result = run_host_baseline(control, "fresh-host")

    assert not result.ok
    assert result.error_code == "baseline_operation_failed"
    assert result.evidence == {"paths": []}
