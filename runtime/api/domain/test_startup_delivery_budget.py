"""Regressions for the composed startup-delivery measurement.

A per-artifact budget cannot answer the question that decides whether a rule
is in force: does the *combined* text a surface is handed fit the channel
carrying it. A packet inside its own budget still arrives truncated when the
block it rides is many times the harness's inline ceiling, which is exactly
what happened — 106.8 KB of composed hook reply into an 8 KiB channel, with
the harness persisting the body to a file and showing a preview from the top.

Covers:

- Every harness gets a row per startup channel, naming the surfaces that row
  covers and the files contributing to it.
- Truncation ceilings and ratchets stay distinguishable: the inline ceilings
  come from the harness contract, the root-rules ceiling from the observed
  Codex cut.
- ``packets.check`` folds drift, both packet axes, and delivery into one
  verdict, and reports ``ok`` false when any of them is over.
- ``packets.startup_delivery.get`` is registered, client-local, CLI-routed.
- Compact packet depth is a strict subset of full, and closes by naming the
  command that renders its own full form.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.hook_inline_context import inline_context_bytes_for_harness
from yoke_contracts.startup_context_budget import (
    ROOT_RULES_TRUNCATION_BYTES,
    STARTUP_CHANNELS,
    estimated_tokens,
    root_rules_bytes,
)
from yoke_core.domain import startup_delivery_budget as delivery
from yoke_core.domain.agents_render_conditional import HARNESS_IDS
from yoke_core.domain.schema_api_context import render_role_packet
from yoke_core.domain.schema_api_context_render import (
    PACKET_DETAIL_COMPACT,
    PACKET_DETAIL_FULL,
)


def _repo_root() -> Path:
    from runtime.api.domain.test_agents_render_workspace_fixtures import (
        resolve_live_repo_root,
    )

    return resolve_live_repo_root()


@pytest.fixture(scope="module")
def report() -> dict:
    return delivery.startup_delivery_report(_repo_root())


def test_every_harness_gets_every_channel(report: dict) -> None:
    seen = {(row["harness_id"], row["channel"]) for row in report["channels"]}
    assert seen == {
        (harness, channel)
        for harness in HARNESS_IDS
        for channel in STARTUP_CHANNELS
    }


def test_each_row_names_the_surfaces_its_payload_reaches(report: dict) -> None:
    """CLI and desktop share one payload, so the row says so rather than
    leaving a reader to wonder whether the desktop case was measured."""
    for row in report["channels"]:
        assert row["surfaces"], f"{row['harness_id']}/{row['channel']}"
        for surface in row["surfaces"]:
            assert surface.startswith(f"{row['harness_id']}-")
        assert any(s.endswith("-cli") for s in row["surfaces"])


def test_root_rules_rows_name_their_contributing_files(report: dict) -> None:
    for row in report["channels"]:
        if row["channel"] != "root_rules":
            continue
        paths = [c["path"] for c in row["contributors"]]
        assert "AGENTS.md" in paths
        if row["harness_id"] == "claude":
            assert "runtime/harness/claude/rules/session.md" in paths
        assert row["bytes"] == sum(c["bytes"] for c in row["contributors"])


def test_inline_ceilings_come_from_the_harness_contract(report: dict) -> None:
    from yoke_contracts.executor_labels import canonical_harness_id

    for row in report["channels"]:
        if row["channel"] == "inline_hook":
            assert row["budget"] == inline_context_bytes_for_harness(
                canonical_harness_id(row["harness_id"])
            )


def test_codex_root_rules_bound_is_the_observed_cut() -> None:
    """Codex injects AGENTS.md through a channel with a measured cut.

    Claude has no observed cut on this channel — a session was observed
    receiving 157,991 bytes of rules verbatim — so its number is a ratchet
    and must not be mistaken for a ceiling.
    """
    assert root_rules_bytes("codex") == ROOT_RULES_TRUNCATION_BYTES
    assert root_rules_bytes("claude") > ROOT_RULES_TRUNCATION_BYTES


def test_headroom_and_tokens_derive_from_usage(report: dict) -> None:
    for row in report["channels"]:
        assert row["headroom"] == row["budget"] - row["bytes"]
        assert row["over_budget"] is (row["bytes"] > row["budget"])
        assert row["estimated_tokens"] == estimated_tokens(row["bytes"])


def test_over_budget_lines_name_every_offending_channel(report: dict) -> None:
    offenders = {
        (row["harness_id"], row["channel"])
        for row in report["channels"]
        if row["over_budget"]
    }
    assert len(report["over_budget"]) == len(offenders)
    for harness, channel in offenders:
        assert any(
            line.startswith(f"{harness} {channel} spends")
            for line in report["over_budget"]
        )


def test_live_repo_delivers_inside_every_channel(report: dict) -> None:
    """The live tree fits every startup channel it has to reach."""
    assert report["over_budget"] == []


def test_orientation_block_is_the_inline_contributor(report: dict) -> None:
    for row in report["channels"]:
        if row["channel"] == "inline_hook":
            assert [c["path"] for c in row["contributors"]] == [
                "session orientation block"
            ]


def test_compact_packet_is_a_strict_subset_of_full() -> None:
    for role in ("main_agent", "engineer_agent"):
        compact = render_role_packet(role, detail=PACKET_DETAIL_COMPACT)
        full = render_role_packet(role, detail=PACKET_DETAIL_FULL)
        assert len(compact.encode("utf-8")) < len(full.encode("utf-8"))
        for line in compact.splitlines():
            if line.strip() and not line.startswith("_Compact depth."):
                assert line in full, line


def test_compact_packet_names_the_command_for_its_own_notes() -> None:
    compact = render_role_packet("main_agent", detail=PACKET_DETAIL_COMPACT)
    assert "--detail full" in compact
    assert "yoke packets render --role main_agent --topic core" in compact


def test_compact_packet_keeps_every_table_and_column() -> None:
    """Compact drops the notes, never the names an agent could confabulate."""
    from yoke_core.domain import schema_api_context_seed as seed

    compact = render_role_packet("main_agent", detail=PACKET_DETAIL_COMPACT)
    for topic in seed.ROLE_TOPICS["main_agent"]:
        for table in seed.TOPIC_TABLES[topic]:
            assert f"`{table}`" in compact, table


def test_unknown_detail_is_refused_by_name() -> None:
    with pytest.raises(ValueError) as caught:
        render_role_packet("main_agent", detail="terse")
    assert "terse" in str(caught.value)
    assert PACKET_DETAIL_COMPACT in str(caught.value)


def _check(payload: dict) -> object:
    from yoke_core.domain.handlers import orchestration_packets as handler

    return handler.handle_packets_check(
        FunctionCallRequest(
            function="packets.check.run",
            actor=ActorContext(session_id="test-session"),
            target=TargetRef(kind="global"),
            payload=payload,
        )
    )


def test_check_folds_drift_budgets_and_delivery() -> None:
    outcome = _check({"target_root": str(_repo_root())})
    assert outcome.primary_success is True
    result = outcome.result_payload
    assert result["drift"] == []
    assert result["over_budget"] == []
    assert result["ok"] is True
    assert result["packet_budget"]["roles"]
    assert result["startup_delivery"]["channels"]


def test_check_is_not_ok_when_a_channel_is_over(monkeypatch) -> None:
    """Correct-but-undeliverable must fail the check.

    Reporting only seed drift is what let a packet pass its own gate while
    spending thirteen times the bytes its channel accepts.
    """
    from yoke_core.domain.handlers import orchestration_packets as handler

    def _over(_root) -> dict:
        return {
            "target_root": "/tmp",
            "channels": [],
            "over_budget": ["codex root_rules spends 99999 bytes"],
        }

    monkeypatch.setattr(
        "yoke_core.domain.startup_delivery_budget.startup_delivery_report", _over
    )
    outcome = handler.handle_packets_check(
        FunctionCallRequest(
            function="packets.check.run",
            actor=ActorContext(session_id="test-session"),
            target=TargetRef(kind="global"),
            payload={"target_root": "/tmp"},
        )
    )
    result = outcome.result_payload
    assert result["ok"] is False
    assert any("99999 bytes" in line for line in result["over_budget"])
    assert any(delivery.DELIVERY_READ_COMMAND in line for line in result["over_budget"])


def test_handler_reports_a_measurement_failure_instead_of_raising(monkeypatch) -> None:
    def _boom(_root) -> dict:
        raise RuntimeError("tree unreadable")

    monkeypatch.setattr(
        "yoke_core.domain.startup_delivery_budget.startup_delivery_report", _boom
    )
    outcome = _check({"target_root": str(_repo_root())})
    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "downstream_failure"
    assert "tree unreadable" in outcome.error.message


def test_delivery_handler_returns_the_report() -> None:
    from yoke_core.domain.handlers import (
        orchestration_startup_delivery as handler,
    )

    outcome = handler.handle_packets_startup_delivery_get(
        FunctionCallRequest(
            function="packets.startup_delivery.get",
            actor=ActorContext(session_id="test-session"),
            target=TargetRef(kind="global"),
            payload={"target_root": str(_repo_root())},
        )
    )
    assert outcome.primary_success is True
    handler.PacketsStartupDeliveryGetResponse.model_validate(outcome.result_payload)


def test_delivery_cli_route_and_client_local_scope_are_registered() -> None:
    from yoke_core.domain.function_authz_scope_client_local import CLIENT_LOCAL_BY_ID
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY

    function_id, adapter = SUBCOMMAND_REGISTRY[
        ("packets", "startup-delivery", "get")
    ]
    assert function_id == "packets.startup_delivery.get"
    assert callable(adapter)
    assert "packets.startup_delivery.get" in CLIENT_LOCAL_BY_ID


def test_delivery_adapter_inventory_row_names_the_read_command() -> None:
    from yoke_core.api.service_client_structured_api_adapter_inventory import (
        adapter_index,
    )

    entry = adapter_index()["packets.startup_delivery.get"]
    assert entry.read_shape is True
    assert entry.cli_invocation.startswith(delivery.DELIVERY_READ_COMMAND)


def test_delivery_human_writer_prints_a_row_per_channel() -> None:
    from yoke_cli.commands.adapters.packets import _startup_delivery_writer

    class _Response:
        result = {
            "target_root": "/repo",
            "channels": [
                {
                    "harness_id": "codex",
                    "channel": "root_rules",
                    "bytes": 99999,
                    "budget": 32768,
                    "headroom": -67231,
                    "estimated_tokens": 25000,
                    "over_budget": True,
                    "contributors": [],
                    "surfaces": ["codex-cli"],
                }
            ],
            "over_budget": ["codex root_rules spends 99999 bytes"],
        }

    out = io.StringIO()
    _startup_delivery_writer(_Response(), out, io.StringIO())
    text = out.getvalue()
    assert "/repo" in text
    assert "codex" in text and "root_rules" in text
    assert "OVER" in text


def test_orientation_block_does_not_inline_the_packet_body() -> None:
    """Orientation rides the inline hook channel, smallest at 8 KiB.

    Inlining the packet put 106.8 KB into it, so the harness persisted the
    body to a file and showed the model a preview from the top — every rule
    past that preview was in force and unread. Rendered for real against the
    live checkout rather than a fixture, because the bytes that matter are
    the ones this tree actually delivers.
    """
    from yoke_contracts.hook_inline_context import INLINE_CONTEXT_BYTES
    from yoke_core.domain.session_orientation import render_orientation

    block = render_orientation({"session_id": "sess-measure"}, _repo_root())
    assert block
    assert "**Schema cheat sheet:**" not in block
    assert "yoke packets render --role main_agent" in block
    assert len(block.encode("utf-8")) < min(INLINE_CONTEXT_BYTES.values())
