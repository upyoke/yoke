"""CLI for schema/API context packet rendering and checks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from yoke_contracts.startup_context_budget import budget_phrase
from yoke_core.domain import schema_api_context_seed as seed
from yoke_core.domain.schema_api_context_packet_budget import (
    BUDGET_READ_COMMAND,
    check_aggregate_bytes,
    check_aggregate_size,
    check_role_packet_bytes,
    check_role_packet_size,
)
from yoke_core.domain.schema_api_context import (
    detect_seed_drift,
    render_role_packet,
    render_topic_packet,
)
from yoke_core.domain.schema_api_context_render import (
    PACKET_DETAIL_COMPACT,
    PACKET_DETAILS,
)
from yoke_core.domain.startup_delivery_budget import (
    DELIVERY_READ_COMMAND,
    startup_delivery_report,
)


def _cli_render(args: argparse.Namespace) -> int:
    if args.topic is not None:
        sys.stdout.write(
            render_topic_packet(args.topic, role=args.role, detail=args.detail)
        )
        return 0
    sys.stdout.write(render_role_packet(args.role, detail=args.detail))
    return 0


def _report_lines(label: str, used: int, budget: int) -> None:
    sys.stderr.write(
        f"SIZE: {label} has {used} lines (budget {budget}). Read every "
        f"role's usage and headroom with `{BUDGET_READ_COMMAND}`.\n"
    )


def _report_bytes(label: str, used: int, budget: int, *, command: str) -> None:
    sys.stderr.write(
        f"SIZE: {label} spends {budget_phrase(used, budget)}. "
        f"Read every surface's usage and headroom with `{command}`.\n"
    )


def _check_packet_budgets() -> int:
    """Refuse on either axis, naming which one and by how much."""
    rc = 0
    for role in seed.ROLE_TOPICS:
        lines, line_budget = check_role_packet_size(role)
        if lines > line_budget:
            _report_lines(f"role={role} packet", lines, line_budget)
            rc = 1
        used, budget = check_role_packet_bytes(role)
        if used > budget:
            _report_bytes(
                f"role={role} packet", used, budget, command=BUDGET_READ_COMMAND
            )
            rc = 1
    total_lines, line_budget = check_aggregate_size()
    if total_lines > line_budget:
        _report_lines("aggregate packets", total_lines, line_budget)
        rc = 1
    total_bytes, byte_budget = check_aggregate_bytes()
    if total_bytes > byte_budget:
        _report_bytes(
            "aggregate packets", total_bytes, byte_budget, command=BUDGET_READ_COMMAND
        )
        rc = 1
    return rc


def _check_startup_delivery(target_root: Optional[str]) -> int:
    """Refuse when any harness's composed startup payload exceeds its channel.

    A packet inside its own budget still arrives truncated when the block
    carrying it is larger than the channel, so the combined payload is
    checked here rather than left to the per-artifact budgets.
    """
    if target_root is None:
        return 0
    report = startup_delivery_report(Path(target_root))
    for line in report["over_budget"]:
        sys.stderr.write(
            f"DELIVERY: {line}. Read every channel's contributors with "
            f"`{DELIVERY_READ_COMMAND}`.\n"
        )
    return 1 if report["over_budget"] else 0


def _cli_check(args: argparse.Namespace) -> int:
    rc = 0
    drift = detect_seed_drift()
    if drift:
        for line in drift:
            print(f"DRIFT: {line}", file=sys.stderr)
        rc = 1
    rc = max(rc, _check_packet_budgets())
    rc = max(rc, _check_startup_delivery(args.target_root))
    if rc == 0:
        print("schema_api_context: no drift detected.")
    return rc


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="schema_api_context")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_render = sub.add_parser("render", help="render a role or role/topic packet")
    p_render.add_argument("--role", required=True, choices=sorted(seed.ROLE_TOPICS))
    p_render.add_argument("--topic", choices=sorted(seed.TOPICS))
    p_render.add_argument(
        "--detail",
        choices=sorted(PACKET_DETAILS),
        default=PACKET_DETAIL_COMPACT,
        help=(
            "compact (default) ships the spine every session needs; full adds "
            "the per-table and per-command notes for the moment they apply"
        ),
    )
    p_render.set_defaults(func=_cli_render)
    p_check = sub.add_parser(
        "check", help="detect seed/live drift and packet or delivery overruns"
    )
    p_check.add_argument(
        "--target-root",
        default=None,
        help=(
            "checkout whose composed startup payload is checked against each "
            "harness channel; omitted skips that check rather than guessing "
            "a root"
        ),
    )
    p_check.set_defaults(func=_cli_check)
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


__all__ = ["main"]
