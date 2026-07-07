"""CLI for Strategize landed-work carry-forward."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional, Sequence

from yoke_core.domain.db_helpers import connect
from yoke_core.domain.strategize_carry_schema import (
    DEFAULT_CARRY_LIMIT,
    DEFAULT_HORIZON_DAYS,
    VALID_STATES,
)
from yoke_core.domain.strategize_carry_state import (
    get_candidate_set,
    mark_items,
    register_new_landings,
)
from yoke_core.domain.strategize_carry_summary import format_summary


def _parse_item_ids(raw: Sequence[str]) -> List[int]:
    result: List[int] = []
    for token in raw:
        if not token:
            continue
        for part in str(token).split(","):
            part = part.strip()
            if not part:
                continue
            if part.upper().startswith("YOK-"):
                part = part[4:]
            try:
                result.append(int(part))
            except ValueError:
                continue
    return result


def _cmd_register_new(args: argparse.Namespace) -> int:
    with connect() as conn:
        new_ids = register_new_landings(
            conn,
            project=args.project,
            horizon_days=args.horizon_days,
            now_iso=args.now,
        )
    if args.json:
        json.dump({"project": args.project, "new_ids": new_ids}, sys.stdout)
        sys.stdout.write("\n")
    else:
        for item_id in new_ids:
            sys.stdout.write(f"YOK-{item_id}\n")
    return 0


def _cmd_candidate_set(args: argparse.Namespace) -> int:
    with connect() as conn:
        candidate_set = get_candidate_set(
            conn,
            project=args.project,
            horizon_days=args.horizon_days,
            carry_limit=args.carry_limit,
            now_iso=args.now,
            new_ids=_parse_item_ids(args.new_ids or []),
        )
    json.dump(candidate_set, sys.stdout, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


def _cmd_summary(args: argparse.Namespace) -> int:
    with connect() as conn:
        new_ids: List[int] = _parse_item_ids(args.new_ids or [])
        if args.register:
            registered = register_new_landings(
                conn,
                project=args.project,
                horizon_days=args.horizon_days,
                now_iso=args.now,
            )
            seen = set(new_ids)
            for item_id in registered:
                if item_id not in seen:
                    new_ids.append(item_id)
                    seen.add(item_id)
        candidate_set = get_candidate_set(
            conn,
            project=args.project,
            horizon_days=args.horizon_days,
            carry_limit=args.carry_limit,
            now_iso=args.now,
            new_ids=new_ids,
        )
    sys.stdout.write(format_summary(candidate_set, display_limit=args.display_limit))
    sys.stdout.write("\n")
    return 0


def _cmd_mark(args: argparse.Namespace) -> int:
    item_ids = _parse_item_ids(args.items or [])
    if not item_ids:
        sys.stderr.write("error: no item ids provided\n")
        return 2
    with connect() as conn:
        changed = mark_items(
            conn,
            project=args.project,
            item_ids=item_ids,
            state=args.state,
            session_id=args.session_id,
            reason=args.reason,
            now_iso=args.now,
        )
    sys.stdout.write(
        f"Marked {changed} item(s) as {args.state} in project {args.project}\n"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.strategize_carry",
        description=(
            "Bounded carry-forward for Strategize landed-work review. "
            "See the strategize-carry contract doc for the full details."
        ),
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    common_horizon = argparse.ArgumentParser(add_help=False)
    common_horizon.add_argument("--project", required=True)
    common_horizon.add_argument(
        "--horizon-days",
        type=int,
        default=DEFAULT_HORIZON_DAYS,
    )
    common_horizon.add_argument(
        "--carry-limit",
        type=int,
        default=DEFAULT_CARRY_LIMIT,
    )
    common_horizon.add_argument(
        "--now",
        help="Override the ISO timestamp used for horizon math (tests only).",
    )

    p_reg = sub.add_parser("register-new", parents=[common_horizon])
    p_reg.add_argument("--json", action="store_true")
    p_reg.set_defaults(func=_cmd_register_new)

    p_cs = sub.add_parser("candidate-set", parents=[common_horizon])
    p_cs.add_argument("--pretty", action="store_true")
    p_cs.add_argument(
        "--new-ids",
        nargs="*",
        default=[],
        help="Item ids previously returned from register-new.",
    )
    p_cs.set_defaults(func=_cmd_candidate_set)

    p_sum = sub.add_parser("summary", parents=[common_horizon])
    p_sum.add_argument("--register", action="store_true", default=True)
    p_sum.add_argument(
        "--no-register",
        dest="register",
        action="store_false",
        help="Skip register-new before building the summary.",
    )
    p_sum.add_argument(
        "--new-ids",
        nargs="*",
        default=[],
        help="Item ids previously returned from register-new.",
    )
    p_sum.add_argument("--display-limit", type=int, default=10)
    p_sum.set_defaults(func=_cmd_summary)

    p_mark = sub.add_parser("mark", parents=[common_horizon])
    p_mark.add_argument("--state", choices=sorted(VALID_STATES), required=True)
    p_mark.add_argument("--session-id")
    p_mark.add_argument("--reason")
    p_mark.add_argument("--items", nargs="+", required=True, help="Item ids.")
    p_mark.set_defaults(func=_cmd_mark)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
