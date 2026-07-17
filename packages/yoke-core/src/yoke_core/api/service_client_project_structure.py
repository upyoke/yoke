"""Service-client command surface for the Project Structure aggregate.

Thin passthroughs to :mod:`yoke_core.domain.project_structure`.  The
domain module owns validation, envelope grammar, op-list application, and
storage writes; this module only translates the CLI shell used by harness
skills (``project-structure-get``, ``project-structure-patch``,
``project-structure-seed``) into domain calls.

The two surfaces (db-router and service-client) remain in lockstep so
operators and skills can use either entry point interchangeably for the
same read/write contracts (project-structure deliverable).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence

from yoke_core.domain import project_structure as ps


def cmd_project_structure_get(argv: Sequence[str]) -> int:
    """Read whole structure or a family slice as JSON."""
    parser = argparse.ArgumentParser(
        prog="service-client project-structure-get",
    )
    parser.add_argument("project_id")
    parser.add_argument("--family")
    args = parser.parse_args(list(argv))
    try:
        result = ps.read_structure(args.project_id, family=args.family)
    except ps.ValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _load_patch_input(stdin: bool, ops_file: Optional[str]) -> Dict[str, Any]:
    if stdin == bool(ops_file):
        raise ps.UsageError("patch requires exactly one of --stdin or --ops-file.")
    if stdin:
        raw = sys.stdin.read()
    else:
        assert ops_file is not None
        with open(ops_file, "r", encoding="utf-8") as fh:
            raw = fh.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ps.UsageError(f"patch input is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ps.UsageError("patch input must be a JSON object with an 'ops' array.")
    if "ops" not in data:
        raise ps.UsageError("patch input must include 'ops'.")
    return data


def cmd_project_structure_patch(argv: Sequence[str]) -> int:
    """Apply an imperative op list atomically."""
    parser = argparse.ArgumentParser(
        prog="service-client project-structure-patch",
    )
    parser.add_argument("project_id")
    parser.add_argument("--stdin", action="store_true")
    parser.add_argument("--ops-file")
    parser.add_argument("--actor")
    args = parser.parse_args(list(argv))
    try:
        payload = _load_patch_input(args.stdin, args.ops_file)
    except ps.UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    try:
        result = ps.apply_patch(
            args.project_id,
            ops=payload["ops"],
            actor=args.actor or payload.get("actor"),
        )
    except (ps.ValidationError, ps.UsageError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_project_structure_seed(argv: Sequence[str]) -> int:
    """Seed a project with legible default entries (idempotent)."""
    parser = argparse.ArgumentParser(
        prog="service-client project-structure-seed",
    )
    parser.add_argument("project_id")
    args = parser.parse_args(list(argv))
    try:
        result = ps.cmd_seed(args.project_id)
    except (ps.ValidationError, ps.UsageError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0
