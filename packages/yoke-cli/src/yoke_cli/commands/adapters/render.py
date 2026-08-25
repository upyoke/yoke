"""``yoke agents render`` / ``yoke packets ...`` / ``yoke board data get``.

Render-family flag adapters:

* ``agents.render.run`` — write the substrate agent prompts.
* ``agents.render.check`` — detect drift between rendered + canonical.
* ``packets.render.run`` — render a single LLM packet role.
* ``packets.check.run`` — verify packet rendering drift.
* ``packets.budget.get`` — read packet line budgets, usage, and headroom.
* ``board.data.get`` — inspect the recorded board query payload.
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
    "agents_render", "agents_render_check",
    "packets_render", "packets_check", "packets_budget_get", "board_data_get",
    "AGENTS_RENDER_USAGE", "AGENTS_RENDER_CHECK_USAGE",
    "PACKETS_RENDER_USAGE", "PACKETS_CHECK_USAGE", "PACKETS_BUDGET_GET_USAGE",
    "BOARD_DATA_GET_USAGE",
]


AGENTS_RENDER_USAGE = (
    "yoke agents render [--target-root PATH] [--dry-run] "
    "[--session-id S] [--json]"
)


def agents_render(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke agents render", description=AGENTS_RENDER_USAGE,
    )
    parser.add_argument("--target-root", dest="target_root", default=None,
                        help="Optional repo-root override.")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="Compute write actions without persisting.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, AGENTS_RENDER_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"dry_run": bool(parsed.dry_run)}
    if parsed.target_root:
        payload["target_root"] = parsed.target_root
    # Repo-tree renderer: must run where the tree lives, never relayed
    # server-side (a relayed render resolves client paths on the server
    # filesystem — 13011/13014).
    return dispatch_and_emit(
        function_id="agents.render.run",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        local_only=True,
    )


AGENTS_RENDER_CHECK_USAGE = (
    "yoke agents render check [--target-root PATH] [--session-id S] [--json]"
)


def agents_render_check(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke agents render check", description=AGENTS_RENDER_CHECK_USAGE,
    )
    parser.add_argument("--target-root", dest="target_root", default=None,
                        help="Optional repo-root override.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, AGENTS_RENDER_CHECK_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.target_root:
        payload["target_root"] = parsed.target_root
    return dispatch_and_emit(
        function_id="agents.render.check",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        local_only=True,
    )


PACKETS_RENDER_USAGE = (
    "yoke packets render --role NAME [--session-id S] [--json]"
)


def packets_render(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke packets render", description=PACKETS_RENDER_USAGE,
    )
    parser.add_argument("--role", required=True,
                        help="Packet role (e.g. 'main_agent', 'engineer_agent').")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PACKETS_RENDER_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="packets.render.run",
        target=TargetRef(kind="global"),
        payload={"role": parsed.role},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        local_only=True,
    )


PACKETS_CHECK_USAGE = (
    "yoke packets check [--session-id S] [--json]"
)


def packets_check(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke packets check", description=PACKETS_CHECK_USAGE,
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PACKETS_CHECK_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="packets.check.run",
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        local_only=True,
    )


PACKETS_BUDGET_GET_USAGE = (
    "yoke packets budget get [--session-id S] [--json]"
)


def _packet_budget_writer(response, stdout, _stderr) -> None:
    """Print one row per packet role, then the aggregate corpus row."""
    result = response.result or {}
    roles = result.get("roles") or []
    print(
        f"packet line budgets — per role {result.get('per_role_budget')}, "
        f"aggregate {result.get('aggregate_budget')}",
        file=stdout,
    )
    print(f"{'ROLE':<20}{'LINES':>7}{'BUDGET':>8}{'HEADROOM':>10}{'CHARS':>9}",
          file=stdout)
    for row in roles:
        flag = "  OVER" if row.get("over_budget") else ""
        print(
            f"{row.get('role', ''):<20}{row.get('lines', 0):>7}"
            f"{row.get('budget', 0):>8}{row.get('headroom', 0):>10}"
            f"{row.get('characters', 0):>9}{flag}",
            file=stdout,
        )
    agg_flag = "  OVER" if result.get("aggregate_over_budget") else ""
    print(
        f"{'aggregate':<20}{result.get('aggregate_lines', 0):>7}"
        f"{result.get('aggregate_budget', 0):>8}"
        f"{result.get('aggregate_headroom', 0):>10}"
        f"{result.get('aggregate_characters', 0):>9}{agg_flag}",
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


BOARD_DATA_GET_USAGE = (
    "yoke board data get [--scope NAME] [--session-id S] [--json]"
)


def board_data_get(args: List[str]) -> int:
    """Fetch the board's recorded data payload (operator-debug surface).

    The production consumer is the ``yoke board rebuild`` composition,
    which resolves DB-backed project policy and the checkout's zen vision
    count; this bare adapter fetches the default-config plan for inspection.
    """
    parser = argparse.ArgumentParser(
        prog="yoke board data get", description=BOARD_DATA_GET_USAGE,
    )
    parser.add_argument("--scope", default="all",
                        help="Project scope (slug, id, or 'all').")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, BOARD_DATA_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, _stderr) -> None:
        result = response.result or {}
        print(
            f"board data v{result.get('version')} scope={result.get('scope')} "
            f"entries={result.get('entry_count')}",
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="board.data.get",
        target=TargetRef(kind="global"),
        payload={"scope": parsed.scope},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )
