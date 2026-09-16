"""``yoke packets ...`` flag adapters.

* ``packets.render.run`` — render one packet role, or one topic within it, at
  the compact depth that ships or the full depth read on demand.
* ``packets.check.run`` — seed drift plus both packet budget axes plus every
  harness startup channel over its ceiling.
* ``packets.budget.get`` — per-role and aggregate line/byte budgets, usage,
  and headroom.
* ``packets.startup_delivery.get`` — what each harness startup channel
  actually delivers, against that channel's ceiling.

Split from :mod:`render`, which holds the agent-adapter and board routes and
is at the authored-file line cap.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "packets_render", "packets_check", "packets_budget_get",
    "packets_startup_delivery_get",
    "PACKETS_RENDER_USAGE", "PACKETS_CHECK_USAGE", "PACKETS_BUDGET_GET_USAGE",
    "PACKETS_STARTUP_DELIVERY_GET_USAGE",
]


PACKETS_RENDER_USAGE = (
    "yoke packets render --role NAME [--topic NAME] [--detail compact|full] "
    "[--session-id S] [--json]"
)


def packets_render(args: List[str]) -> int:
    """Render one packet role, or one topic within it, at a chosen depth.

    ``--detail compact`` (the default) is the spine that ships at session
    start. ``--detail full`` adds the per-table and per-command notes, which
    is what a compact block's closing pointer sends an agent here for.
    """
    parser = argparse.ArgumentParser(
        prog="yoke packets render", description=PACKETS_RENDER_USAGE,
    )
    parser.add_argument("--role", required=True,
                        help="Packet role (e.g. 'main_agent', 'engineer_agent').")
    parser.add_argument("--topic", default=None,
                        help="Render one topic of that role instead of all of them.")
    parser.add_argument("--detail", default=None,
                        help="compact (default) or full; full adds the notes.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PACKETS_RENDER_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"role": parsed.role}
    if parsed.topic:
        payload["topic"] = parsed.topic
    if parsed.detail:
        payload["detail"] = parsed.detail
    return dispatch_and_emit(
        function_id="packets.render.run",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        local_only=True,
    )


PACKETS_CHECK_USAGE = (
    "yoke packets check [--target-root PATH] [--session-id S] [--json]"
)


def _packets_check_writer(response, stdout, stderr) -> None:
    """Print the verdict: drift lines, budget overruns, then one summary."""
    result = response.result or {}
    for line in result.get("drift") or []:
        print(f"DRIFT: {line}", file=stderr)
    for line in result.get("over_budget") or []:
        print(f"SIZE: {line}", file=stderr)
    if result.get("ok"):
        print("packets check: no drift, every budget within range.", file=stdout)


def packets_check(args: List[str]) -> int:
    """Check the packets for seed drift and for both delivery budget axes.

    Exits non-zero when the packets are correct but undeliverable, because a
    rule that does not reach the model is not in force.
    """
    parser = argparse.ArgumentParser(
        prog="yoke packets check", description=PACKETS_CHECK_USAGE,
    )
    parser.add_argument("--target-root", dest="target_root", default=None,
                        help="Checkout to measure; defaults to this one.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PACKETS_CHECK_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.target_root:
        payload["target_root"] = parsed.target_root
    return dispatch_and_emit(
        function_id="packets.check.run",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_packets_check_writer,
        local_only=True,
    )


PACKETS_BUDGET_GET_USAGE = (
    "yoke packets budget get [--session-id S] [--json]"
)


def _packet_budget_writer(response, stdout, _stderr) -> None:
    """Print both budgeted axes per packet role, then the aggregate corpus."""
    result = response.result or {}
    print(
        "packet budgets — per role "
        f"{result.get('per_role_line_budget')} lines / "
        f"{result.get('per_role_byte_budget')} bytes, aggregate "
        f"{result.get('aggregate_line_budget')} lines / "
        f"{result.get('aggregate_byte_budget')} bytes",
        file=stdout,
    )
    print(
        f"{'ROLE':<20}{'LINES':>7}{'HEADROOM':>10}"
        f"{'BYTES':>9}{'HEADROOM':>10}{'~TOKENS':>9}",
        file=stdout,
    )
    for row in result.get("roles") or []:
        flag = "  OVER" if row.get("over_budget") else ""
        print(
            f"{row.get('role', ''):<20}{row.get('lines', 0):>7}"
            f"{row.get('line_headroom', 0):>10}{row.get('bytes', 0):>9}"
            f"{row.get('byte_headroom', 0):>10}"
            f"{row.get('estimated_tokens', 0):>9}{flag}",
            file=stdout,
        )
    agg_flag = "  OVER" if result.get("aggregate_over_budget") else ""
    print(
        f"{'aggregate':<20}{result.get('aggregate_lines', 0):>7}"
        f"{result.get('aggregate_line_headroom', 0):>10}"
        f"{result.get('aggregate_bytes', 0):>9}"
        f"{result.get('aggregate_byte_headroom', 0):>10}"
        f"{result.get('aggregate_estimated_tokens', 0):>9}{agg_flag}",
        file=stdout,
    )


def packets_budget_get(args: List[str]) -> int:
    """Report each packet role's line budget, live usage, and headroom.

    Named by the budget-exceeded messages in ``schema_api_context_cli`` and
    the packet-size tests, so an agent that hits the cap has one command to
    run. Client-local like its ``packets render`` / ``packets check``
    siblings: it measures the packets this checkout renders, which is what a
    seed edit needs to see.
    """
    parser = argparse.ArgumentParser(
        prog="yoke packets budget get", description=PACKETS_BUDGET_GET_USAGE,
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PACKETS_BUDGET_GET_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="packets.budget.get",
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_packet_budget_writer,
        local_only=True,
    )


PACKETS_STARTUP_DELIVERY_GET_USAGE = (
    "yoke packets startup-delivery get [--target-root PATH] [--session-id S] "
    "[--json]"
)


def _startup_delivery_writer(response, stdout, _stderr) -> None:
    """Print one row per harness channel, then every channel over budget."""
    result = response.result or {}
    print(f"startup delivery — {result.get('target_root', '')}", file=stdout)
    print(
        f"{'HARNESS':<12}{'CHANNEL':<14}{'BYTES':>9}{'BUDGET':>9}"
        f"{'HEADROOM':>10}{'~TOKENS':>9}",
        file=stdout,
    )
    for row in result.get("channels") or []:
        flag = "  OVER" if row.get("over_budget") else ""
        print(
            f"{row.get('harness_id', ''):<12}{row.get('channel', ''):<14}"
            f"{row.get('bytes', 0):>9}{row.get('budget', 0):>9}"
            f"{row.get('headroom', 0):>10}"
            f"{row.get('estimated_tokens', 0):>9}{flag}",
            file=stdout,
        )
    for line in result.get("over_budget") or []:
        print(f"OVER: {line}", file=stdout)


def packets_startup_delivery_get(args: List[str]) -> int:
    """Report each harness startup channel's delivered payload and budget.

    Named by the delivery-exceeded messages in ``schema_api_context_cli``, so
    a surface that cannot receive its instructions has one command to run.
    Client-local: it measures the files and blocks this checkout renders.
    """
    parser = argparse.ArgumentParser(
        prog="yoke packets startup-delivery get",
        description=PACKETS_STARTUP_DELIVERY_GET_USAGE,
    )
    parser.add_argument("--target-root", dest="target_root", default=None,
                        help="Checkout to measure; defaults to this one.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, PACKETS_STARTUP_DELIVERY_GET_USAGE
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.target_root:
        payload["target_root"] = parsed.target_root
    return dispatch_and_emit(
        function_id="packets.startup_delivery.get",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_startup_delivery_writer,
        local_only=True,
    )
