"""Regressions for the packet line-budget read surface.

Covers:

- Per-role and aggregate packet sizes stay within budget (the enforced cap).
- The reported usage is the number the caps compare against, per role and
  in aggregate — a read surface that disagreed with the gate would send an
  agent trimming a packet the gate never measured.
- Headroom, over-budget flags, and role coverage.
- ``packets.budget.get`` is registered, client-local, and CLI-routed.
- Every budget-exceeded message names the read command, so an agent that
  hits the cap has one command to run.
"""

from __future__ import annotations

import io

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import schema_api_context as sac
from yoke_core.domain import schema_api_context_cli as sac_cli
from yoke_core.domain import schema_api_context_seed as seed
from yoke_core.domain import schema_api_context_packet_budget as budget


@pytest.fixture(scope="module")
def report() -> dict:
    """Render the corpus once; every assertion below reads this report."""
    return budget.packet_budget_report()


@pytest.mark.parametrize("role", sorted(seed.ROLE_TOPICS))
def test_role_packet_within_size_budget(role: str) -> None:
    size, cap = sac.check_role_packet_size(role)
    assert size <= cap, (
        f"role={role} packet has {size} lines, budget is {cap}. Run "
        f"`{budget.BUDGET_READ_COMMAND}` for every role's headroom, then "
        "either trim the seed (preferred — packet content is for fast "
        "agent reference, not a comprehensive schema doc) or increase "
        "PACKET_LINE_BUDGET_PER_ROLE in schema_api_context_seed.py with "
        "an explicit rationale."
    )


def test_aggregate_packet_size_within_budget() -> None:
    total, cap = sac.check_aggregate_size()
    assert total <= cap, (
        f"aggregate packet size is {total} lines, budget is {cap}. Run "
        f"`{budget.BUDGET_READ_COMMAND}` for the per-role breakdown, then "
        "see PACKET_LINE_BUDGET_AGGREGATE in schema_api_context_seed.py."
    )


def test_report_covers_every_role_in_sorted_order(report: dict) -> None:
    assert [row["role"] for row in report["roles"]] == sorted(seed.ROLE_TOPICS)


@pytest.mark.parametrize("role", sorted(seed.ROLE_TOPICS))
def test_reported_usage_is_the_number_the_role_gate_enforces(
    report: dict, role: str
) -> None:
    row = next(r for r in report["roles"] if r["role"] == role)
    size, cap = sac.check_role_packet_size(role)
    assert (row["lines"], row["budget"]) == (size, cap)


def test_reported_aggregate_is_the_number_the_aggregate_gate_enforces(
    report: dict,
) -> None:
    total, cap = sac.check_aggregate_size()
    assert (report["aggregate_lines"], report["aggregate_budget"]) == (total, cap)


def test_headroom_and_over_budget_derive_from_usage(report: dict) -> None:
    for row in report["roles"]:
        assert row["headroom"] == row["budget"] - row["lines"]
        assert row["over_budget"] is (row["lines"] > row["budget"])
        assert row["characters"] > row["lines"]
    assert report["aggregate_headroom"] == (
        report["aggregate_budget"] - report["aggregate_lines"]
    )
    assert report["aggregate_over_budget"] is (
        report["aggregate_lines"] > report["aggregate_budget"]
    )


def test_aggregate_totals_sum_the_role_rows(report: dict) -> None:
    assert report["aggregate_lines"] == sum(r["lines"] for r in report["roles"])
    assert report["aggregate_characters"] == sum(
        r["characters"] for r in report["roles"]
    )


def test_packet_line_count_counts_newlines() -> None:
    assert budget.packet_line_count("a\nb\nc\n") == 3
    assert budget.packet_line_count("") == 0


def test_over_budget_role_message_names_the_read_command(capsys, monkeypatch) -> None:
    monkeypatch.setattr(sac_cli, "check_role_packet_size", lambda role: (999, 425))
    monkeypatch.setattr(sac_cli, "check_aggregate_size", lambda: (10, 2630))
    assert sac_cli.main(["check"]) == 1
    err = capsys.readouterr().err
    assert "SIZE: role=" in err
    assert budget.BUDGET_READ_COMMAND in err


def test_over_budget_aggregate_message_names_the_read_command(
    capsys, monkeypatch
) -> None:
    monkeypatch.setattr(sac_cli, "check_role_packet_size", lambda role: (1, 425))
    monkeypatch.setattr(sac_cli, "check_aggregate_size", lambda: (99999, 2630))
    assert sac_cli.main(["check"]) == 1
    err = capsys.readouterr().err
    assert "SIZE: aggregate packets total" in err
    assert budget.BUDGET_READ_COMMAND in err


def test_handler_returns_the_report(monkeypatch) -> None:
    from yoke_core.domain.handlers import orchestration_packet_budget as handler

    stub = {
        "roles": [],
        "per_role_budget": 425,
        "aggregate_budget": 2630,
        "aggregate_lines": 0,
        "aggregate_characters": 0,
        "aggregate_headroom": 2630,
        "aggregate_over_budget": False,
    }
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


def test_human_writer_prints_a_row_per_role_and_the_aggregate() -> None:
    from yoke_cli.commands.adapters.render import _packet_budget_writer

    class _Response:
        result = {
            "roles": [
                {
                    "role": "main_agent",
                    "lines": 400,
                    "budget": 425,
                    "headroom": 25,
                    "characters": 9000,
                    "over_budget": False,
                },
                {
                    "role": "boss_agent",
                    "lines": 430,
                    "budget": 425,
                    "headroom": -5,
                    "characters": 9500,
                    "over_budget": True,
                },
            ],
            "per_role_budget": 425,
            "aggregate_budget": 2630,
            "aggregate_lines": 830,
            "aggregate_characters": 18500,
            "aggregate_headroom": 1800,
            "aggregate_over_budget": False,
        }

    out = io.StringIO()
    _packet_budget_writer(_Response(), out, io.StringIO())
    text = out.getvalue()
    assert "main_agent" in text and "boss_agent" in text
    assert "aggregate" in text
    assert text.count("OVER") == 1
