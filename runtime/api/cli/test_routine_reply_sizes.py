"""Per-command routine budgets, with realistic populated projections."""

import io
from types import SimpleNamespace

import pytest

from yoke_cli.transport.output_limit import read_output_scope


@pytest.mark.parametrize(
    "command,budget",
    [
        ("qa", 3_000),
        ("sessions", 3_000),
        ("launch", 1_500),
        ("message", 700),
        ("packet", 2_000),
    ],
)
def test_measured_routine_read_sizes(command, budget):
    from yoke_cli.commands.adapters.qa_plan_listing import write_plan_rows
    from yoke_cli.commands.adapters.session_control_roster import write_roster_summary
    from yoke_cli.commands.adapters.session_control_common import (
        write_message_detail_result,
    )
    from yoke_cli.commands.adapters.session_control_launch_output import (
        write_launch_result,
    )
    from yoke_cli.commands.adapters.packets import write_packet_summary

    writers = {
        "qa": write_plan_rows,
        "sessions": write_roster_summary,
        "message": write_message_detail_result,
        "packet": write_packet_summary,
    }
    result = {
        "qa": {
            "rows": [
                {
                    "id": n,
                    "slug": "example-plan-" + str(n),
                    "name": "N" * 300,
                    "case_count": 3,
                    "last_outcome": "passed",
                }
                for n in range(25)
            ],
            "next_offset": 25,
        },
        "sessions": {
            "rows": [
                {
                    "session_id": f"00000000-0000-0000-0000-{n:012}",
                    "liveness": "active",
                    "executor_surface": "codex-cli",
                    "current_item": "APP-7",
                }
                for n in range(25)
            ],
            "next_offset": 25,
        },
        "message": {
            "message": {
                "message_id": "message-example",
                "body": "Instruction. " * 2_000,
                "state": "pending",
            }
        },
        "packet": {
            "role": "main_agent",
            "topic": "core",
            "detail": "compact",
            "body": "\n".join(
                f"### Topic {n}\n" + "reference " * 200 for n in range(10)
            ),
        },
        "launch": {
            "launch": {
                "launch_id": "launch-example",
                "state": "succeeded",
                "registered_session_id": "session-example",
                "message_id": "message-example",
                "level_placement": {"candidates": [{"detail": "x" * 10_000}]},
            }
        },
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


@pytest.mark.parametrize(
    "command,budget", [("holder", 1_000), ("item", 2_000), ("deployment", 2_000)]
)
def test_other_measured_routine_reply_sizes(command, budget, monkeypatch):
    from yoke_cli.transport.human_values import write_human
    from yoke_cli.commands.adapters import deployment_reads

    result = {
        "holder": {
            "holders": [
                {
                    "claim_id": 1,
                    "session_id": "session-example",
                    "scope": {"public_ref": "APP-7"},
                    "lane_worktrees": ["checkout/lane"],
                }
            ]
        },
        "item": {
            "item": {
                "public_ref": "APP-7",
                "title": "Short routine item",
                "status": "implementing",
                "workflow": {
                    "id": "dash",
                    "version": 1,
                    "stage_id": "implementing",
                    "next_skill_id": "dash",
                },
                "claim": {"session_id": "session-example"},
                "worktrees": [],
            },
            "read": "yoke items detail get APP-7 --full",
        },
        "deployment": {
            "rows": [
                {
                    "id": f"run-example-{n}",
                    "project": "example",
                    "status": "executing",
                    "current_stage": "qa",
                }
                for n in range(7)
            ]
        },
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


def test_explicit_full_packet_detail_is_complete():
    from yoke_cli.commands.adapters.packets import write_packet_summary

    body = "Packet schema detail " * 2_000
    out = io.StringIO()
    with read_output_scope([], "packets.render.run"):
        write_packet_summary(
            SimpleNamespace(result={"body": body, "detail": "full"}), out, io.StringIO()
        )
    assert out.getvalue() == body + "\n"


@pytest.mark.parametrize(
    "rows", [[[1, "one"], [2, "two"], [3, "three"]], [[None, True, False]]]
)
def test_scalar_rows_have_one_lossless_line_each(rows):
    from yoke_cli.transport.human_values import scalar, write_human

    out = io.StringIO()
    write_human(rows, out)
    assert [line.split(" | ") for line in out.getvalue().splitlines()] == [
        [scalar(cell) for cell in row] for row in rows
    ]


def test_scalar_lists_use_one_named_line():
    from yoke_cli.transport.human_values import write_human

    out = io.StringIO()
    write_human({"columns": ["one", "two"]}, out)
    assert out.getvalue() == "columns: one | two\n"


@pytest.mark.parametrize("cell", ["a|b", "a\nb", "a\rb"])
@pytest.mark.parametrize("shape", ["list", "rows", "records"])
def test_delimited_or_multiline_cells_keep_complete_values(cell, shape):
    from yoke_cli.transport.human_values import write_human

    value = {"list": [cell], "rows": [[cell]], "records": [{"value": cell}]}[shape]
    out = io.StringIO()
    write_human(value, out)
    text = out.getvalue()
    assert "entry 1:" in text
    assert (
        cell.replace("\n", "\n  ") in text
        or cell.replace("\n", "\n    ") in text
        or cell.replace("\n", "\n      ") in text
    )
