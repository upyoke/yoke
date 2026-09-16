"""Regressions for the packet budget read surface.

Two axes are budgeted and the byte axis is the one that decides delivery: a
packet can sit under a line cap while spending six figures of bytes, because
nothing stops one line from carrying thousands of them. Covers:

- Per-role and aggregate sizes stay within budget on both axes.
- Reported usage is the number each gate compares against — a read surface
  that disagreed with the gate would send an agent trimming a packet the gate
  never measured.
- Bytes are counted as UTF-8 bytes, not characters, because that is what the
  channels these figures feed actually measure.
- Headroom, over-budget flags, and role coverage on both axes.
- ``packets.budget.get`` is registered, client-local, and CLI-routed.
- Every budget-exceeded message names the read command, so an agent that hits
  a cap has one command to run.
"""

from __future__ import annotations

import io

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import schema_api_context_cli as sac_cli
from yoke_core.domain import schema_api_context_seed as seed
from yoke_core.domain import schema_api_context_packet_budget as budget


@pytest.fixture(scope="module")
def report() -> dict:
    """Render the corpus once; every assertion below reads this report."""
    return budget.packet_budget_report()


def _row(report: dict, role: str) -> dict:
    return next(r for r in report["roles"] if r["role"] == role)


@pytest.mark.parametrize("role", sorted(seed.ROLE_TOPICS))
def test_role_packet_within_line_budget(role: str) -> None:
    lines, cap = budget.check_role_packet_size(role)
    assert lines <= cap, (
        f"role={role} packet has {lines} lines, budget is {cap}. Run "
        f"`{budget.BUDGET_READ_COMMAND}` for every role's headroom, then "
        "either trim the seed or raise PACKET_LINE_BUDGET_PER_ROLE with an "
        "explicit rationale."
    )


@pytest.mark.parametrize("role", sorted(seed.ROLE_TOPICS))
def test_role_packet_within_byte_budget(role: str) -> None:
    spent, cap = budget.check_role_packet_bytes(role)
    assert spent <= cap, (
        f"role={role} packet spends {spent} bytes, budget is {cap}. Run "
        f"`{budget.BUDGET_READ_COMMAND}`, then either trim the seed or raise "
        "PACKET_BYTE_BUDGET_PER_ROLE with an explicit rationale. The byte "
        "axis is the one a delivery channel measures."
    )


def test_aggregate_packet_size_within_both_budgets() -> None:
    total_lines, line_cap = budget.check_aggregate_size()
    assert total_lines <= line_cap, (
        f"aggregate packets total {total_lines} lines, budget is {line_cap}; "
        f"see PACKET_LINE_BUDGET_AGGREGATE and `{budget.BUDGET_READ_COMMAND}`."
    )
    total_bytes, byte_cap = budget.check_aggregate_bytes()
    assert total_bytes <= byte_cap, (
        f"aggregate packets spend {total_bytes} bytes, budget is {byte_cap}; "
        f"see PACKET_BYTE_BUDGET_AGGREGATE and `{budget.BUDGET_READ_COMMAND}`."
    )


def test_report_covers_every_role_in_sorted_order(report: dict) -> None:
    assert [row["role"] for row in report["roles"]] == sorted(seed.ROLE_TOPICS)


@pytest.mark.parametrize("role", sorted(seed.ROLE_TOPICS))
def test_reported_usage_is_the_number_each_role_gate_enforces(
    report: dict, role: str
) -> None:
    row = _row(report, role)
    assert (row["lines"], row["line_budget"]) == budget.check_role_packet_size(role)
    assert (row["bytes"], row["byte_budget"]) == budget.check_role_packet_bytes(role)


def test_reported_aggregate_is_the_number_each_aggregate_gate_enforces(
    report: dict,
) -> None:
    assert (
        report["aggregate_lines"],
        report["aggregate_line_budget"],
    ) == budget.check_aggregate_size()
    assert (
        report["aggregate_bytes"],
        report["aggregate_byte_budget"],
    ) == budget.check_aggregate_bytes()


def test_headroom_and_over_budget_derive_from_usage(report: dict) -> None:
    for row in report["roles"]:
        assert row["line_headroom"] == row["line_budget"] - row["lines"]
        assert row["byte_headroom"] == row["byte_budget"] - row["bytes"]
        assert row["over_line_budget"] is (row["lines"] > row["line_budget"])
        assert row["over_byte_budget"] is (row["bytes"] > row["byte_budget"])
        assert row["over_budget"] is (
            row["over_line_budget"] or row["over_byte_budget"]
        )
        assert row["bytes"] > row["lines"]
    assert report["aggregate_line_headroom"] == (
        report["aggregate_line_budget"] - report["aggregate_lines"]
    )
    assert report["aggregate_byte_headroom"] == (
        report["aggregate_byte_budget"] - report["aggregate_bytes"]
    )
    assert report["aggregate_over_budget"] is (
        report["aggregate_over_line_budget"]
        or report["aggregate_over_byte_budget"]
    )


def test_aggregate_totals_sum_the_role_rows(report: dict) -> None:
    assert report["aggregate_lines"] == sum(r["lines"] for r in report["roles"])
    assert report["aggregate_bytes"] == sum(r["bytes"] for r in report["roles"])


def test_packet_line_count_counts_newlines() -> None:
    assert budget.packet_line_count("a\nb\nc\n") == 3
    assert budget.packet_line_count("") == 0


def test_packet_byte_count_measures_utf8_bytes_not_characters() -> None:
    """A multi-byte character costs what it costs on the wire.

    The packets are full of em dashes and arrows, so counting characters
    understates every figure the delivery channels compare against.
    """
    body = "a—b"
    assert len(body) == 3
    assert budget.packet_byte_count(body) == 5


def test_estimated_tokens_accompany_every_byte_figure(report: dict) -> None:
    from yoke_contracts.startup_context_budget import estimated_tokens

    for row in report["roles"]:
        assert row["estimated_tokens"] == estimated_tokens(row["bytes"])
    assert report["aggregate_estimated_tokens"] == estimated_tokens(
        report["aggregate_bytes"]
    )


def test_over_line_budget_message_names_the_read_command(
    capsys, monkeypatch
) -> None:
    monkeypatch.setattr(sac_cli, "check_role_packet_size", lambda role: (999, 425))
    monkeypatch.setattr(sac_cli, "check_role_packet_bytes", lambda role: (1, 2))
    monkeypatch.setattr(sac_cli, "check_aggregate_size", lambda: (10, 2630))
    monkeypatch.setattr(sac_cli, "check_aggregate_bytes", lambda: (10, 2630))
    assert sac_cli.main(["check"]) == 1
    err = capsys.readouterr().err
    assert "SIZE: role=" in err
    assert "has 999 lines" in err
    assert budget.BUDGET_READ_COMMAND in err


def test_over_byte_budget_message_names_both_axes_in_words(
    capsys, monkeypatch
) -> None:
    """The refusal states bytes and the token estimate, never bytes alone."""
    monkeypatch.setattr(sac_cli, "check_role_packet_size", lambda role: (1, 425))
    monkeypatch.setattr(
        sac_cli, "check_role_packet_bytes", lambda role: (99999, 30000)
    )
    monkeypatch.setattr(sac_cli, "check_aggregate_size", lambda: (10, 2630))
    monkeypatch.setattr(sac_cli, "check_aggregate_bytes", lambda: (10, 2630))
    assert sac_cli.main(["check"]) == 1
    err = capsys.readouterr().err
    assert "99999 bytes" in err
    assert "tokens) against a budget of 30000 bytes" in err
    assert budget.BUDGET_READ_COMMAND in err


def test_over_budget_aggregate_message_names_the_read_command(
    capsys, monkeypatch
) -> None:
    monkeypatch.setattr(sac_cli, "check_role_packet_size", lambda role: (1, 425))
    monkeypatch.setattr(sac_cli, "check_role_packet_bytes", lambda role: (1, 2))
    monkeypatch.setattr(sac_cli, "check_aggregate_size", lambda: (99999, 2630))
    monkeypatch.setattr(sac_cli, "check_aggregate_bytes", lambda: (10, 2630))
    assert sac_cli.main(["check"]) == 1
    err = capsys.readouterr().err
    assert "SIZE: aggregate packets has 99999 lines" in err
    assert budget.BUDGET_READ_COMMAND in err


def _stub_report() -> dict:
    return {
        "roles": [],
        "per_role_line_budget": 425,
        "per_role_byte_budget": 30000,
        "aggregate_line_budget": 2630,
        "aggregate_byte_budget": 180000,
        "aggregate_lines": 0,
        "aggregate_bytes": 0,
        "aggregate_estimated_tokens": 0,
        "aggregate_line_headroom": 2630,
        "aggregate_byte_headroom": 180000,
        "aggregate_over_line_budget": False,
        "aggregate_over_byte_budget": False,
        "aggregate_over_budget": False,
    }


def test_handler_returns_the_report(monkeypatch) -> None:
    from yoke_core.domain.handlers import orchestration_packet_budget as handler

    stub = _stub_report()
    monkeypatch.setattr(budget, "packet_budget_report", lambda: stub)
    outcome = handler.handle_packets_budget_get(
        FunctionCallRequest(
            function="packets.budget.get",
            actor=ActorContext(session_id="test-session"),
            target=TargetRef(kind="global"),
        )
    )
    assert outcome.primary_success is True
    assert outcome.result_payload == stub
    handler.PacketsBudgetGetResponse.model_validate(outcome.result_payload)


def test_handler_reports_a_render_failure_instead_of_raising(monkeypatch) -> None:
    from yoke_core.domain.handlers import orchestration_packet_budget as handler

    def _boom() -> dict:
        raise RuntimeError("seed unreadable")

    monkeypatch.setattr(budget, "packet_budget_report", _boom)
    outcome = handler.handle_packets_budget_get(
        FunctionCallRequest(
            function="packets.budget.get",
            actor=ActorContext(session_id="test-session"),
            target=TargetRef(kind="global"),
        )
    )
    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "downstream_failure"
    assert "seed unreadable" in outcome.error.message


def test_cli_route_and_client_local_scope_are_registered() -> None:
    from yoke_core.domain.function_authz_scope_client_local import CLIENT_LOCAL_BY_ID
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    function_id, adapter = SUBCOMMAND_REGISTRY[("packets", "budget", "get")]
    assert function_id == "packets.budget.get"
    assert callable(adapter)
    assert "packets.budget.get" in CLIENT_LOCAL_BY_ID


def test_adapter_inventory_row_names_the_read_command() -> None:
    from yoke_core.api.service_client_structured_api_adapter_inventory import (
        adapter_index,
    )

    entry = adapter_index()["packets.budget.get"]
    assert entry.read_shape is True
    assert entry.cli_invocation.startswith(budget.BUDGET_READ_COMMAND)


def test_human_writer_prints_both_axes_per_role_and_the_aggregate() -> None:
    from yoke_cli.commands.adapters.packets import _packet_budget_writer

    class _Response:
        result = dict(
            _stub_report(),
            roles=[
                {
                    "role": "main_agent",
                    "lines": 400,
                    "line_headroom": 25,
                    "bytes": 9000,
                    "byte_headroom": 21000,
                    "estimated_tokens": 2250,
                    "over_budget": False,
                },
                {
                    "role": "boss_agent",
                    "lines": 430,
                    "line_headroom": -5,
                    "bytes": 9500,
                    "byte_headroom": -500,
                    "estimated_tokens": 2375,
                    "over_budget": True,
                },
            ],
            aggregate_lines=830,
            aggregate_bytes=18500,
            aggregate_estimated_tokens=4625,
        )

    out = io.StringIO()
    _packet_budget_writer(_Response(), out, io.StringIO())
    text = out.getvalue()
    assert "main_agent" in text and "boss_agent" in text
    assert "aggregate" in text
    assert "2250" in text and "4625" in text
    assert text.count("OVER") == 1
