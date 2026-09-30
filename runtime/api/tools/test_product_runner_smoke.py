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
