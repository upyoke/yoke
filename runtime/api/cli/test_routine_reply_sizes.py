"""Per-command routine budgets, with realistic populated projections."""

import io
from types import SimpleNamespace

import pytest

from yoke_cli.transport.output_limit import read_output_scope


@pytest.mark.parametrize("command,budget", [
    ("qa", 3_000), ("sessions", 3_000), ("launch", 1_500),
    ("message", 700), ("packet", 2_000),
])
def test_measured_routine_read_sizes(command, budget):
    from yoke_cli.commands.adapters.qa_plan_listing import write_plan_rows
    from yoke_cli.commands.adapters.session_control_roster import write_roster_summary
    from yoke_cli.commands.adapters.session_control_common import write_message_detail_result
    from yoke_cli.commands.adapters.session_control_launch_output import write_launch_result
    from yoke_cli.commands.adapters.packets import write_packet_summary

    writers = {
        "qa": write_plan_rows, "sessions": write_roster_summary,
        "message": write_message_detail_result, "packet": write_packet_summary,
    }
    result = {
        "qa": {"rows": [{"id": n, "slug": "example-plan-" + str(n), "name": "N" * 300,
                         "case_count": 3, "last_outcome": "passed"} for n in range(25)], "next_offset": 25},
        "sessions": {"rows": [{"session_id": f"00000000-0000-0000-0000-{n:012}",
                     "liveness": "active", "executor_surface": "codex-cli", "current_item": "APP-7"} for n in range(25)], "next_offset": 25},
        "message": {"message": {"message_id": "message-example", "body": "Instruction. " * 2_000, "state": "pending"}},
        "packet": {"role": "main_agent", "topic": "core", "detail": "compact",
                   "body": "\n".join(f"### Topic {n}\n" + "reference " * 200 for n in range(10))},
        "launch": {"launch": {"launch_id": "launch-example", "state": "succeeded",
                   "registered_session_id": "session-example", "message_id": "message-example",
                   "level_placement": {"candidates": [{"detail": "x" * 10_000}]}}},
    }[command]
    out = io.StringIO()
    with read_output_scope([], "session_control.launch.get"):
        if command == "launch":
            write_launch_result(result, out)
        else:
            writers[command](SimpleNamespace(result=result), out, io.StringIO())
    text = out.getvalue()
    assert len(text.encode()) <= budget, text
    assert "saved" not in text.lower()
    assert "--full" in text or " body" in text


@pytest.mark.parametrize("command,budget", [("holder", 1_000), ("item", 2_000), ("deployment", 2_000)])
def test_other_measured_routine_reply_sizes(command, budget, monkeypatch):
    from yoke_cli.transport.human_values import write_human
    from yoke_cli.commands.adapters import deployment_reads

    result = {
        "holder": {"holders": [{"claim_id": 1, "session_id": "session-example", "scope": {"public_ref": "APP-7"}, "lane_worktrees": ["checkout/lane"]}]},
        "item": {"item": {"public_ref": "APP-7", "title": "Short routine item", "status": "implementing", "workflow": {"id": "dash", "version": 1, "stage_id": "implementing", "next_skill_id": "dash"}, "claim": {"session_id": "session-example"}, "worktrees": []}, "read": "yoke items detail get APP-7 --full"},
        "deployment": {"rows": [{"id": f"run-example-{n}", "project": "example", "status": "executing", "current_stage": "qa"} for n in range(7)]},
    }[command]
    out = io.StringIO()
    if command == "deployment":
        def dispatch(**kwargs):
            kwargs["human_writer"](SimpleNamespace(result=result), out, io.StringIO())
            return 0
        monkeypatch.setattr(deployment_reads, "dispatch_and_emit", dispatch)
        assert deployment_reads.deployment_runs_list(["--project", "example"]) == 0
    else:
        write_human(result, out)
    assert len(out.getvalue().encode()) <= budget
