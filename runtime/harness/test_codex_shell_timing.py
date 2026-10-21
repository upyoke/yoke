"""Native Codex command timing crosses the same client-fact boundary everywhere."""

import json

import pytest

from yoke_contracts.codex_shell_timing import command_duration_ms
from yoke_harness.hooks.client_facts import collect_client_facts


def command(call_id="exec-command", duration=None):
    return {
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "item": {
                "type": "CommandExecution",
                "id": call_id,
                "duration": duration
                if duration is not None
                else {"secs": 11, "nanos": 240_000_000},
            },
        },
    }


def payload(tmp_path, records):
    transcript = tmp_path / "rollout.jsonl"
    transcript.write_text("\n".join(json.dumps(record) for record in records))
    return {
        "transcript_path": str(transcript),
        "tool_use_id": "exec-command",
        "tool_name": "Bash",
        "tool_input": {"command": "build"},
    }


def test_background_command_uses_native_duration_not_item_wall(tmp_path):
    item = command()
    item["payload"].update(started_at_ms=1000, completed_at_ms=356000)
    data = payload(
        tmp_path, [item, command("another-command", {"secs": 99, "nanos": 0})]
    )
    assert command_duration_ms(data) == 11240
    facts = collect_client_facts(
        "PostToolUse", data, "codex", ["yoke_core.domain.observe"]
    )
    assert facts["duration_ms"] == 11240
    # These are the identical facts merged locally and sent as HTTPS payload_extra.
    from yoke_core.domain.observe_parsing import parse_hook_event
    from yoke_core.domain.observe_event_emission import build_envelope

    rec = parse_hook_event(
        {**data, **facts}, session_id="session", hook_event="PostToolUse"
    )
    assert rec.duration_ms == 11240
    assert (
        build_envelope(rec)["context"]["detail"]["timing_status"] == "native_duration"
    )


@pytest.mark.parametrize(
    "duration",
    [
        None,
        {},
        {"secs": -1, "nanos": 0},
        {"secs": True, "nanos": 0},
        {"secs": 1, "nanos": 1_000_000_000},
        {"secs": 1.5, "nanos": 0},
    ],
)
def test_invalid_native_duration_does_not_invent_timing(tmp_path, duration):
    record = command()
    record["payload"]["item"]["duration"] = duration
    assert command_duration_ms(payload(tmp_path, [record])) is None


def test_missing_unrelated_and_partial_records_leave_fallback(tmp_path):
    data = payload(tmp_path, [command("unrelated"), [], {"type": "event_msg"}])
    with open(data["transcript_path"], "a") as handle:
        handle.write('\n{"payload":')
    assert command_duration_ms(data) is None
    assert (
        command_duration_ms({**data, "transcript_path": str(tmp_path / "missing")})
        is None
    )
    assert command_duration_ms({**data, "tool_use_id": ""}) is None


@pytest.mark.parametrize(
    "executor,event",
    [
        ("cursor", "PostToolUse"),
        ("claude-code", "PostToolUse"),
        ("codex", "PreToolUse"),
    ],
)
def test_other_harnesses_and_starts_keep_their_existing_timing(
    tmp_path, executor, event
):
    data = payload(tmp_path, [command()])
    facts = collect_client_facts(event, data, executor, ["yoke_core.domain.observe"])
    assert "duration_ms" not in facts


def test_zero_and_fractional_durations_and_supplied_native_value(tmp_path):
    assert (
        command_duration_ms(
            payload(tmp_path, [command(duration={"secs": 0, "nanos": 0})])
        )
        == 0
    )
    assert (
        command_duration_ms(
            payload(tmp_path, [command(duration={"secs": 0, "nanos": 1_500_000})])
        )
        == 2
    )
    assert command_duration_ms({"duration_ms": 25}) == 25
