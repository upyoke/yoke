"""CLI for the Project Structure aggregate.

Argparse parser plus command dispatch. Maps domain exceptions to the exit
code contract declared in the parent module's docstring (0 success, 1
error, 2 usage).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from yoke_core.domain.project_structure import (
    ATTACHMENT_BRANCHES,
    MULTIPLICITIES,
    NET_NEW_FAMILIES,
    PATH_SELECTOR_KINDS,
    UsageError,
    ValidationError,
    cmd_init,
)
from yoke_core.domain.project_structure_seeds import cmd_seed
from yoke_core.domain.project_structure import read_structure
from yoke_core.domain.project_structure_write import apply_patch


_USAGE = """\
Usage: python3 -m yoke_core.domain.project_structure <subcmd> [args...]

Subcommands:
  init                                Create/upgrade Project Structure tables (idempotent)
  get <project-id> [--family F]       Whole structure or family slice (JSON)
  patch <project-id> (--stdin | --ops-file PATH) [--actor A]
                                      Apply an op list atomically
  seed <project-id>                   Seed legible default entries (idempotent)
  family-list                         Print the frozen family vocabulary"""


def _parse_patch_input(stdin: bool, ops_file: Optional[str]) -> Dict[str, Any]:
    if stdin == bool(ops_file):
        raise UsageError("patch requires exactly one of --stdin or --ops-file.")
    if stdin:
        raw = sys.stdin.read()
    else:
        assert ops_file is not None  # type narrowing
        raw = Path(ops_file).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UsageError(f"patch input is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise UsageError("patch input must be a JSON object with an 'ops' array.")
    if "ops" not in data:
        raise UsageError("patch input missing required 'ops' array.")
    return data


def cmd_get(args: argparse.Namespace) -> int:
    try:
        result = read_structure(args.project_id, family=args.family)
    except ValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_patch(args: argparse.Namespace) -> int:
    try:
        payload = _parse_patch_input(args.stdin, args.ops_file)
    except UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    try:
        result = apply_patch(
            args.project_id,
            ops=payload["ops"],
            actor=args.actor or payload.get("actor"),
        )
    except (ValidationError, UsageError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_seed_cli(args: argparse.Namespace) -> int:
    try:
        result = cmd_seed(args.project_id)
    except (ValidationError, UsageError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_family_list(_: argparse.Namespace) -> int:
    registry = {
        "net_new": {
            name: dict(env) for name, env in NET_NEW_FAMILIES.items()
        },
        "attachment_branches": list(ATTACHMENT_BRANCHES),
        "path_selector_kinds": list(PATH_SELECTOR_KINDS),
        "multiplicities": list(MULTIPLICITIES),
    }
    print(json.dumps(registry, indent=2, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.project_structure",
        description=(
            "Project Structure aggregate — frozen constitution and "
            "family instantiation."
        ),
    )
    sub = parser.add_subparsers(dest="subcmd")

    sub.add_parser("init", help="Create/upgrade tables (idempotent)")

    p_get = sub.add_parser("get", help="Read whole structure or family slice")
    p_get.add_argument("project_id")
    p_get.add_argument("--family")

    p_patch = sub.add_parser("patch", help="Apply an op list atomically")
    p_patch.add_argument("project_id")
    p_patch.add_argument("--stdin", action="store_true")
    p_patch.add_argument("--ops-file")
    p_patch.add_argument("--actor")

    p_seed = sub.add_parser("seed", help="Seed legible default entries")
    p_seed.add_argument("project_id")

    sub.add_parser("family-list", help="Print the frozen family vocabulary")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args_in = argv if argv is not None else sys.argv[1:]
    if not args_in:
        print(_USAGE, file=sys.stderr)
        return 2
    parser = _build_parser()
    args = parser.parse_args(args_in)
    if args.subcmd is None:
        print(_USAGE, file=sys.stderr)
        return 2
    dispatch = {
        "init": lambda _a: (cmd_init(), 0)[1],
        "get": cmd_get,
        "patch": cmd_patch,
        "seed": cmd_seed_cli,
        "family-list": cmd_family_list,
    }
    handler = dispatch.get(args.subcmd)
    if handler is None:  # pragma: no cover - argparse guards this
        print(_USAGE, file=sys.stderr)
        return 2
    return handler(args)
