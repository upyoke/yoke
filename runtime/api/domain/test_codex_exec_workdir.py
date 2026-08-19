"""Codex PreToolUse omits exec_command.workdir; recover it from the rollout."""

from __future__ import annotations

import json

from yoke_core.hooks.codex_exec_workdir import (
    enrich_payload_workdir,
    extract_exec_workdir,
    lookup_transcript_workdir,
)
from yoke_core.hooks.codex_payload import _parse_payload


def test_extract_exec_workdir_reads_js_object_shape():
    body = (
        'const r = await tools.exec_command({cmd:"touch probe-guard-check.txt",'
        'workdir:"/Users/beebauman/yoke/.worktrees/YOK-2244",'
        "yield_time_ms:10000});"
    )
    assert extract_exec_workdir(body) == (
        "/Users/beebauman/yoke/.worktrees/YOK-2244"
    )


def test_extract_exec_workdir_reads_json_object_shape():
    body = (
        'tools.exec_command({"cmd":"pwd","workdir":"/checkout/lane",'
        '"yield_time_ms":10000})'
    )
    assert extract_exec_workdir(body) == "/checkout/lane"


def test_extract_exec_workdir_absent_returns_empty():
    assert extract_exec_workdir('tools.exec_command({cmd:"pwd"})') == ""


def test_lookup_and_enrich_inject_tool_input_workdir(tmp_path):
    transcript = tmp_path / "rollout.jsonl"
    call_id = "call_QUKruklZWk5Uh3G7iSNR7iBA"
    lane = "/Users/beebauman/yoke/.worktrees/YOK-2244"
    transcript.write_text(
        json.dumps({
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "call_id": call_id,
                "name": "exec",
                "input": (
                    'tools.exec_command({cmd:"touch probe-guard-check.txt",'
                    'workdir:"' + lane + '"})'
                ),
            },
        })
        + "\n",
        encoding="utf-8",
    )
    assert lookup_transcript_workdir(str(transcript), call_id) == lane

    payload = {
        "cwd": "/Users/beebauman/yoke",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_use_id": call_id,
        "transcript_path": str(transcript),
        "tool_input": {"command": "touch probe-guard-check.txt"},
    }
    enriched = enrich_payload_workdir(payload)
    assert enriched["tool_input"]["workdir"] == lane
    assert enriched["cwd"] == "/Users/beebauman/yoke"


def test_parse_payload_enriches_missing_workdir(tmp_path):
    transcript = tmp_path / "rollout.jsonl"
    call_id = "call_probe"
    lane = "/lane"
    transcript.write_text(
        json.dumps({
            "payload": {
                "call_id": call_id,
                "input": 'tools.exec_command({cmd:"ls",workdir:"' + lane + '"})',
            },
        })
        + "\n",
        encoding="utf-8",
    )
    parsed = _parse_payload(json.dumps({
        "tool_name": "Bash",
        "tool_use_id": call_id,
        "transcript_path": str(transcript),
        "cwd": "/session",
        "tool_input": {"command": "ls"},
    }))
    assert parsed["tool_input"]["workdir"] == lane


def test_declared_workdir_is_not_overwritten(tmp_path):
    transcript = tmp_path / "rollout.jsonl"
    transcript.write_text(
        json.dumps({
            "payload": {
                "call_id": "call_1",
                "input": 'workdir:"/from-transcript"',
            },
        })
        + "\n",
        encoding="utf-8",
    )
    payload = {
        "tool_use_id": "call_1",
        "transcript_path": str(transcript),
        "tool_input": {"command": "ls", "workdir": "/already-set"},
    }
    assert enrich_payload_workdir(payload)["tool_input"]["workdir"] == (
        "/already-set"
    )
