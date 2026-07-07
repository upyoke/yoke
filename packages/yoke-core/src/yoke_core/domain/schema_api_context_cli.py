"""CLI for schema/API context packet rendering and checks."""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from yoke_core.domain import schema_api_context_seed as seed
from yoke_core.domain.schema_api_context import (
    check_aggregate_size,
    check_role_packet_size,
    detect_seed_drift,
    render_role_packet,
    render_topic_packet,
)


def _cli_render(args: argparse.Namespace) -> int:
    if args.topic is not None:
        sys.stdout.write(render_topic_packet(args.topic))
        return 0
    sys.stdout.write(render_role_packet(args.role))
    return 0


def _cli_check(_: argparse.Namespace) -> int:
    drift = detect_seed_drift()
    rc = 0
    if drift:
        for line in drift:
            print(f"DRIFT: {line}", file=sys.stderr)
        rc = 1
    for role in seed.ROLE_TOPICS:
        size, budget = check_role_packet_size(role)
        if size > budget:
            print(
                f"SIZE: role={role} packet has {size} lines (budget {budget})",
                file=sys.stderr,
            )
            rc = 1
    total, agg_budget = check_aggregate_size()
    if total > agg_budget:
        print(
            f"SIZE: aggregate packets total {total} lines (budget {agg_budget})",
            file=sys.stderr,
        )
        rc = 1
    if rc == 0:
        print("schema_api_context: no drift detected.")
    return rc


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="schema_api_context")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_render = sub.add_parser("render", help="render a role or role/topic packet")
    p_render.add_argument("--role", required=True, choices=sorted(seed.ROLE_TOPICS))
    p_render.add_argument("--topic", choices=sorted(seed.TOPICS))
    p_render.set_defaults(func=_cli_render)
    p_check = sub.add_parser("check", help="detect seed/live drift and size overruns")
    p_check.set_defaults(func=_cli_check)
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


__all__ = ["main"]
