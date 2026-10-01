"""Fail-closed evidence checks for native hook replay on disposable runners."""

from __future__ import annotations

import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from runtime.api.tools.product_runner_hooks import (
    remap_recording,
    rendered_command,
    require_dispatch,
    require_wire,
)
from runtime.api.tools.product_runner_smoke import (
    Commands,
    SmokeFailure,
    isolated_environment,
    observed_runner,
    require_browser_installation,
)


@pytest.mark.parametrize("stdout", ["", "initialization noise\n{}", "[]"])
def test_document_failure_names_the_step_and_existing_capture(
    tmp_path, monkeypatch, stdout
):
    monkeypatch.setattr(
        "runtime.api.tools.product_runner_smoke.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )
    commands = Commands(tmp_path, {})
    with pytest.raises(SmokeFailure, match="command_json_invalid: step=onboard") as exc:
        commands.document("onboard", ["yoke", "onboard"], cwd=tmp_path)
    capture = tmp_path / "01-onboard.txt"
    assert str(capture) in str(exc.value)
    assert f"stdout:\n{stdout}" in capture.read_text()


def test_command_start_failure_is_captured_and_named(tmp_path, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("executable missing")

    monkeypatch.setattr(
        "runtime.api.tools.product_runner_smoke.subprocess.run", missing
    )
    commands = Commands(tmp_path, {})
    with pytest.raises(SmokeFailure, match="command_start_failed: step=onboard") as exc:
        commands.run("onboard", ["missing"], cwd=tmp_path)
    capture = tmp_path / "01-onboard.txt"
    assert str(capture) in str(exc.value)
    assert "executable missing" in capture.read_text()


def receipt(outcome="allow", *, chain_length=10, timed_out=False):
    return {
        "event_id": "receipt",
        "envelope": json.dumps(
            {
                "hook_event_name": "PreToolUse",
                "context": {
                    "decision_outcome": outcome,
                    "chain_length": chain_length,
                    "timed_out": timed_out,
                },
            }
        ),
    }


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [receipt(chain_length=0)],
        [receipt(timed_out=True)],
        [receipt("timeout_allow")],
    ],
)
def test_cli_success_cannot_substitute_for_evaluation(rows):
    with pytest.raises(ValueError, match="hook_"):
        require_dispatch(rows, outcome="allow")


def test_dispatch_proves_both_decisions():
    assert require_dispatch([receipt()], outcome="allow")["outcome"] == "allow"
    assert require_dispatch([receipt("deny")], outcome="deny")["outcome"] == "deny"


def test_diagnostic_failure_cannot_pass_beside_an_allow_receipt():
    with pytest.raises(ValueError, match="hook_execution_failed"):
        require_dispatch(
            [receipt(), {"event_name": "HookExecutionFailed"}], outcome="allow"
        )


@pytest.mark.parametrize("harness", ["claude", "codex", "cursor"])
def test_empty_success_cannot_substitute_for_denial(harness):
    with pytest.raises(ValueError, match="hook_wire_mismatch"):
        require_wire(
            SimpleNamespace(returncode=0, stdout=""), harness=harness, outcome="deny"
        )


def test_claude_denial_uses_exit_two_and_stderr():
    require_wire(
        SimpleNamespace(returncode=2, stdout="", stderr="BLOCKED: threatened state"),
        harness="claude",
        outcome="deny",
    )
    with pytest.raises(ValueError, match="hook_wire_mismatch"):
        require_wire(
            SimpleNamespace(returncode=2, stdout="BLOCKED", stderr=""),
            harness="claude",
            outcome="deny",
        )


def test_replay_remaps_identity_and_paths_without_flattening_native_structure():
    payload = {
        "session_id": "native",
        "conversation_id": "native",
        "cwd": "/native",
        "tool_name": "Bash",
        "tool_input": {
            "command": "native command",
            "description": "native description",
        },
        "sandbox": "enabled",
    }
    replayed = remap_recording(
        payload, project=Path("/project"), session="fresh", command="git status --short"
    )
    assert replayed["session_id"] == replayed["conversation_id"] == "fresh"
    assert replayed["cwd"] == "/project"
    assert replayed["tool_input"] == {
        "command": "git status --short",
        "description": "native description",
    }
    assert replayed["sandbox"] == "enabled"
    assert payload["tool_input"]["command"] == "native command"


@pytest.mark.parametrize("transcript", [None, "", "/native/transcript.jsonl"])
def test_replay_transcript_identity_matches_session_or_stays_absent(transcript):
    from yoke_contracts.cursor_session_map import transcript_session_id

    replayed = remap_recording(
        {"transcript_path": transcript}, project=Path("/project"), session="fresh"
    )["transcript_path"]
    assert transcript_session_id(replayed or "") == ("fresh" if transcript else "")
    if not transcript:
        assert replayed == transcript


def test_rendered_command_is_consumed_verbatim(tmp_path):
    command = "/bin/sh -c 'env YOKE_ROOT=\"$PWD\" yoke hook evaluate PreToolUse'"
    config = tmp_path / "hooks.json"
    config.write_text(
        json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"command": command}]}]}})
    )
    assert rendered_command(tmp_path, "hooks.json", "PreToolUse") == command


def test_child_environment_excludes_host_authority(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_SESSION_ID", "host-session")
    monkeypatch.setenv("YOKE_PG_DSN", "host-db")
    monkeypatch.setenv("GH_TOKEN", "host-token")
    env = isolated_environment(tmp_path, tmp_path / "venv")
    assert not {"YOKE_SESSION_ID", "YOKE_PG_DSN", "GH_TOKEN", "YOKE_ENV"} & env.keys()
    assert Path(env["YOKE_MACHINE_HOME"]).is_relative_to(tmp_path)


@pytest.mark.parametrize("harness", ["claude", "codex", "cursor"])
def test_native_corpus_has_all_events_without_account_data(harness):
    root = Path(__file__).resolve().parents[3]
    text = (root / "tests/fixtures/harness-sessions" / f"{harness}.json").read_text()
    fixture = json.loads(text)
    assert fixture["provenance"]["harness_version"]
    assert all(
        fixture[key]
        for key in ("session_start", "pre_tool_use_allowed", "pre_tool_use_denied")
    )
    assert not re.search(
        r"[\w.+-]+@[\w.-]+|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9-]{23}|/Users/|/home/|/var/folders/",
        text,
    )
    replayed = remap_recording(
        fixture["session_start"], project=Path("/project"), session="fresh"
    )
    if harness == "cursor":
        assert replayed["workspace_roots"] == ["/project"]


def test_source_test_failure_retains_nested_capture_and_survives_cleanup(tmp_path):
    from runtime.api.tools.product_runner_source_tests import run_source_tests

    home = tmp_path / "home"
    home.mkdir()
    output = tmp_path / "evidence"
    output.mkdir()
    seen = []

    def run(name, argv, *, cwd):
        seen.append((name, argv))
        if name == "pytest-subset":
            (home / "yoke-pytest.raw.failure.log").write_text("pytest diagnostic")
            (Path(commands.env["YOKE_PG_CLUSTER_ROOT"]) / "server.log").write_text(
                "server diagnostic"
            )
            raise ValueError("primary test failure")
        if name == "stop-test-postgres":
            raise RuntimeError("cleanup failure")

    commands = SimpleNamespace(
        env={"YOKE_MACHINE_HOME": str(home)}, output=output, run=run
    )
    with pytest.raises(ValueError, match="primary test failure"):
        run_source_tests(tmp_path, commands)

    assert (output / "yoke-pytest.raw.failure.log").read_text() == "pytest diagnostic"
    assert (output / "server.log").read_text() == "server diagnostic"
    assert seen[1][1][:4] == ["uv", "run", "--frozen", "yoke"]
    assert seen[-1][0] == "stop-test-postgres"


@pytest.mark.parametrize(
    "output",
    [
        "Linux system libraries already present",
        "installing missing Linux system libraries via root; Linux system libraries verified",
        "installing missing Linux system libraries via passwordless sudo",
    ],
)
def test_product_smoke_requires_passwordless_install_and_recheck(tmp_path, output):
    capture = tmp_path / "onboard.txt"
    capture.write_text(output)
    with pytest.raises(SmokeFailure, match="browser_installation_unproven"):
        require_browser_installation({"browser_setup": {"status": "ready"}}, capture)


def test_product_smoke_accepts_recorded_passwordless_installation(tmp_path):
    capture = tmp_path / "onboard.txt"
    capture.write_text(
        "installing missing Linux system libraries via passwordless sudo\n"
        "Linux system libraries verified"
    )
    require_browser_installation({"browser_setup": {"status": "ready"}}, capture)


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("linux", "x86_64", {"os": "Ubuntu 24.04", "architecture": "x86_64"}),
        ("linux", "aarch64", {"os": "Ubuntu 24.04", "architecture": "arm64"}),
        ("darwin", "arm64", {"os": "macOS 26", "architecture": "arm64"}),
        ("linux", "riscv64", {"os": "Ubuntu 24.04", "architecture": "riscv64"}),
    ],
)
def test_runner_identity_uses_declared_architecture_names(
    monkeypatch, system, machine, expected
):
    from runtime.api.tools import product_runner_smoke as runner

    monkeypatch.setattr(runner.sys, "platform", system)
    monkeypatch.setattr(runner.platform, "machine", lambda: machine)
    monkeypatch.setattr(
        runner.platform,
        "freedesktop_os_release",
        lambda: {"NAME": "Ubuntu", "VERSION_ID": "24.04"},
    )
    monkeypatch.setattr(runner.platform, "mac_ver", lambda: ("26.0", (), ""))
    assert observed_runner() == expected
