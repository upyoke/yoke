"""The hook client stamps a Codex command's workdir from its local rollout."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.harness_command_workdir import (
    HARNESS_COMMAND_WORKDIR_SOURCES,
    command_workdir_source,
)
from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS
from yoke_harness.hooks.command_workdir_stamp import (
    exec_command_calls,
    stamp_command_workdir,
    workdir_for_command,
)

LANE = "/Users/operator/yoke/.worktrees/YOK-3610"
MAIN = "/Users/operator/yoke"
CALL_ID = "call_QUKruklZWk5Uh3G7iSNR7iBA"
# A recorded Codex ``exec`` body: two invocations, different workdirs.
EXEC_INPUT = (
    'text(await tools.exec_command({cmd:"yoke ouroboros field-note append '
    "--kind observation --evidence 'it\\'s noted'\",workdir:\"" + MAIN + '",'
    "max_output_tokens:1200}));\n"
    "text(await tools.exec_command({cmd:\"python3 - <<'PY'\\nfrom pathlib "
    'import Path\\np=Path(\'a.py\'); p.write_text(\\"x\\")\\nPY",workdir:"'
    + LANE
    + '",max_output_tokens:1000}));'
)
EDIT_COMMAND = "python3 - <<'PY'\nfrom pathlib import Path\np=Path('a.py'); p.write_text(\"x\")\nPY"


def _rollout(tmp_path, source: str) -> str:
    path = tmp_path / "rollout.jsonl"
    lines = [
        {"type": "session_meta", "payload": {"id": "thread"}},
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "call_id": CALL_ID,
                "name": "exec",
                "input": source,
            },
        },
    ]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return str(path)


def _stdin(transcript: str, command: str, **tool_input) -> str:
    return json.dumps(
        {
            "hook_event_name": "PreToolUse",
            "cwd": MAIN,
            "tool_name": "Bash",
            "tool_use_id": CALL_ID,
            "transcript_path": transcript,
            "tool_input": {"command": command, **tool_input},
        }
    )


def test_every_harness_declares_a_command_workdir_source():
    assert set(HARNESS_COMMAND_WORKDIR_SOURCES) == set(CANONICAL_HARNESS_IDS)
    with pytest.raises(KeyError, match="re-render the harness manifests"):
        command_workdir_source("unknown-harness")


def test_calls_decode_js_string_literals():
    calls = exec_command_calls(EXEC_INPUT)
    assert [call["workdir"] for call in calls] == [MAIN, LANE]
    assert calls[0]["cmd"].endswith("--evidence 'it's noted'")
    assert calls[1]["cmd"] == EDIT_COMMAND


def test_json_quoted_keys_and_workdir_before_cmd():
    source = 'tools.exec_command({"workdir": "/lane", "cmd": "ls"})'
    assert workdir_for_command(source, "ls") == "/lane"


def test_codex_stamp_picks_the_invocation_running_this_command(tmp_path):
    transcript = _rollout(tmp_path, EXEC_INPUT)
    stamped = json.loads(
        stamp_command_workdir(_stdin(transcript, EDIT_COMMAND), "codex")
    )
    assert stamped["tool_input"]["workdir"] == LANE
    assert stamped["cwd"] == MAIN


def test_ambiguous_invocations_stamp_nothing(tmp_path):
    transcript = _rollout(tmp_path, EXEC_INPUT)
    stdin = _stdin(transcript, "a command no invocation ran")
    assert stamp_command_workdir(stdin, "codex") == stdin


def test_single_invocation_without_a_workdir_stamps_nothing(tmp_path):
    transcript = _rollout(tmp_path, 'tools.exec_command({cmd:"ls"})')
    stdin = _stdin(transcript, "ls")
    assert stamp_command_workdir(stdin, "codex") == stdin


def test_declared_workdir_is_kept(tmp_path):
    transcript = _rollout(tmp_path, EXEC_INPUT)
    stdin = _stdin(transcript, EDIT_COMMAND, workdir="/already")
    assert stamp_command_workdir(stdin, "codex") == stdin


@pytest.mark.parametrize("executor", ["claude-code", "cursor", "not-a-harness"])
def test_other_sources_leave_stdin_untouched(tmp_path, executor):
    stdin = _stdin(_rollout(tmp_path, EXEC_INPUT), EDIT_COMMAND)
    assert stamp_command_workdir(stdin, executor) == stdin


def test_missing_rollout_stamps_nothing(tmp_path):
    stdin = _stdin(str(tmp_path / "absent.jsonl"), EDIT_COMMAND)
    assert stamp_command_workdir(stdin, "codex") == stdin
