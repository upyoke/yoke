"""Shepherd domain CLI front door.

Public imports from ``yoke_core.domain.shepherd`` are preserved here while the
implementation lives in focused sibling modules.

CLI usage: ``python3 -m yoke_core.domain.shepherd <subcmd> [args...]``.
"""
from __future__ import annotations

import sys
from typing import List, Optional

from yoke_core.domain.cli_text_file import resolve_text_file
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.shepherd_dependency import (
    VALID_GATE_POINTS,
    VALID_SATISFACTIONS,
    VALID_SOURCES,
    cmd_dependency_add,
    cmd_dependency_reconcile,
    cmd_dependency_remove,
    cmd_dependency_update,
)
from yoke_core.domain.shepherd_dependency_read import cmd_dependency_list
from yoke_core.domain.shepherd_dependency_enrich import cmd_dependency_enrich
from yoke_core.domain.shepherd_init import cmd_init
from yoke_core.domain.shepherd_verdict_log import (
    VALID_DISPOSITIONS,
    cmd_caveat_disposition,
    cmd_caveat_dispositions,
    cmd_shepherd_log,
    cmd_verdict,
)

__all__ = [
    "VALID_DISPOSITIONS",
    "VALID_GATE_POINTS",
    "VALID_SATISFACTIONS",
    "VALID_SOURCES",
    "cmd_caveat_disposition",
    "cmd_caveat_dispositions",
    "cmd_dependency_add",
    "cmd_dependency_enrich",
    "cmd_dependency_list",
    "cmd_dependency_reconcile",
    "cmd_dependency_remove",
    "cmd_dependency_update",
    "cmd_init",
    "cmd_shepherd_log",
    "cmd_verdict",
    "main",
]

_USAGE = """\
Usage: shepherd <subcmd> [args...]

Subcommands:
  init
  verdict <item> <transition> <worker> <verdict> [caveats] [session_id]
  shepherd-log <item_id>
  caveat-disposition <item> <transition> <attempt> <caveat_num> <caveat_text> <disposition> [resolution_details] [verdict_id]
  caveat-dispositions <item>
  dependency-add <dependent> <blocking> <source> [flags] [session_id]
  dependency-update <dependent> <blocking> [flags]
  dependency-reconcile <source> <scope-item> [--gate-point <p>]
  dependency-remove <dependent> <blocking> [session_id]
  dependency-list <item>
  dependency-enrich
"""


def _dependency_add_help() -> str:
    valid_sources = ", ".join(sorted(VALID_SOURCES))
    return f"""\
Usage: shepherd dependency-add <dependent> <blocking> <source> [flags] [session_id]

Positional arguments:
  dependent   YOK-N item that waits for the blocker
  blocking    YOK-N item that blocks the dependent item
  source      Dependency source. Valid values: {valid_sources}

Flags:
  --gate-point <p>
  --satisfaction <s>
  --rationale <text> | --rationale-file <path>
  --evidence <json> | --evidence-file <path>
"""


def _cli_error(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _cli_usage_error(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def _run_dependency_add(conn, rest: list[str]) -> None:
    if rest and rest[0] in {"-h", "--help"}:
        print(_dependency_add_help())
        return
    if len(rest) < 3:
        _cli_usage_error(_dependency_add_help())
    dependent, blocking, source = rest[0], rest[1], rest[2]
    gate_point = satisfaction = rationale = evidence = None
    rationale_file = evidence_file = None
    session_id = None
    i = 3
    while i < len(rest):
        if rest[i] == "--gate-point" and i + 1 < len(rest):
            gate_point = rest[i + 1]
            i += 2
        elif rest[i] == "--satisfaction" and i + 1 < len(rest):
            satisfaction = rest[i + 1]
            i += 2
        elif rest[i] == "--rationale" and i + 1 < len(rest):
            rationale = rest[i + 1]
            i += 2
        elif rest[i] == "--rationale-file" and i + 1 < len(rest):
            rationale_file = rest[i + 1]
            i += 2
        elif rest[i] == "--evidence" and i + 1 < len(rest):
            evidence = rest[i + 1]
            i += 2
        elif rest[i] == "--evidence-file" and i + 1 < len(rest):
            evidence_file = rest[i + 1]
            i += 2
        elif not rest[i].startswith("--"):
            session_id = int(rest[i])
            i += 1
        else:
            _cli_error(f"Error: unknown flag '{rest[i]}'", 1)
    if rationale and rationale_file:
        _cli_usage_error("--rationale and --rationale-file are mutually exclusive")
    if evidence and evidence_file:
        _cli_usage_error("--evidence and --evidence-file are mutually exclusive")
    try:
        rationale = resolve_text_file(rationale, rationale_file, "--rationale-file")
        evidence = resolve_text_file(evidence, evidence_file, "--evidence-file")
    except ValueError as exc:
        _cli_usage_error(f"Error: {exc}")
    cmd_dependency_add(
        conn,
        dependent,
        blocking,
        source,
        gate_point=gate_point or "activation",
        satisfaction=satisfaction,
        rationale=rationale,
        evidence_json=evidence or "{}",
        session_id=session_id,
    )


def _run_dependency_update(conn, rest: list[str]) -> None:
    if len(rest) < 2:
        _cli_usage_error("Usage: shepherd dependency-update <dep> <blk> [flags]")
    dependent, blocking = rest[0], rest[1]
    match_gate_point = gate_point = satisfaction = rationale = rationale_file = None
    i = 2
    while i < len(rest):
        if rest[i] == "--match-gate-point" and i + 1 < len(rest):
            match_gate_point = rest[i + 1]
            i += 2
        elif rest[i] == "--gate-point" and i + 1 < len(rest):
            gate_point = rest[i + 1]
            i += 2
        elif rest[i] == "--satisfaction" and i + 1 < len(rest):
            satisfaction = rest[i + 1]
            i += 2
        elif rest[i] == "--rationale" and i + 1 < len(rest):
            rationale = rest[i + 1]
            i += 2
        elif rest[i] == "--rationale-file" and i + 1 < len(rest):
            rationale_file = rest[i + 1]
            i += 2
        else:
            _cli_error(f"Error: unknown flag '{rest[i]}'", 1)
    if rationale and rationale_file:
        _cli_usage_error("--rationale and --rationale-file are mutually exclusive")
    try:
        rationale = resolve_text_file(rationale, rationale_file, "--rationale-file")
    except ValueError as exc:
        _cli_usage_error(f"Error: {exc}")
    cmd_dependency_update(
        conn,
        dependent,
        blocking,
        match_gate_point,
        gate_point,
        satisfaction,
        rationale,
    )


def _run_dependency_reconcile(conn, rest: list[str]) -> None:
    if len(rest) < 2:
        _cli_usage_error("Usage: shepherd dependency-reconcile <source> <scope-item>")
    source, scope = rest[0], rest[1]
    gate_point_filter = None
    i = 2
    while i < len(rest):
        if rest[i] == "--gate-point" and i + 1 < len(rest):
            gate_point_filter = rest[i + 1]
            i += 2
        else:
            _cli_error(f"Error: unknown flag '{rest[i]}'", 1)
    cmd_dependency_reconcile(conn, source, scope, gate_point_filter)


def main(argv: Optional[List[str]] = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        _cli_usage_error(_USAGE)

    subcmd = args[0]
    rest = args[1:]
    conn = connect()
    try:
        if subcmd == "init":
            print(cmd_init(conn))
        elif subcmd == "verdict":
            if len(rest) < 4:
                _cli_usage_error(
                    "Usage: shepherd verdict <item> <transition> <worker> <verdict> "
                    "[caveats]"
                )
            if len(rest) > 5:
                # Older callers passed a 6th positional that referenced a
                # retired session-id column. Accept and ignore so stale callers
                # don't crash the verdict insert; warn so the operator notices.
                print(
                    "shepherd verdict: ignoring extra positional argument(s); "
                    "this subcommand accepts only [item, transition, worker, "
                    "verdict, caveats].",
                    file=sys.stderr,
                )
            caveats = rest[4] if len(rest) > 4 else None
            print(cmd_verdict(conn, rest[0], rest[1], rest[2], rest[3], caveats))
        elif subcmd == "shepherd-log":
            if not rest:
                _cli_usage_error("Usage: shepherd shepherd-log <item_id>")
            print(cmd_shepherd_log(conn, rest[0]))
        elif subcmd == "caveat-disposition":
            if len(rest) < 6:
                _cli_usage_error(
                    "Usage: shepherd caveat-disposition <item> <transition> <attempt> "
                    "<caveat_num> <caveat_text> <disposition> [resolution_details] [verdict_id]"
                )
            resolution = rest[6] if len(rest) > 6 else None
            verdict_id = int(rest[7]) if len(rest) > 7 else None
            cmd_caveat_disposition(
                conn,
                rest[0],
                rest[1],
                int(rest[2]),
                int(rest[3]),
                rest[4],
                rest[5],
                resolution,
                verdict_id,
            )
        elif subcmd == "caveat-dispositions":
            if not rest:
                _cli_usage_error("Usage: shepherd caveat-dispositions <item>")
            result = cmd_caveat_dispositions(conn, rest[0])
            if result:
                print(result)
        elif subcmd == "dependency-add":
            _run_dependency_add(conn, rest)
        elif subcmd == "dependency-update":
            _run_dependency_update(conn, rest)
        elif subcmd == "dependency-reconcile":
            _run_dependency_reconcile(conn, rest)
        elif subcmd == "dependency-remove":
            if len(rest) < 2:
                _cli_usage_error("Usage: shepherd dependency-remove <dep> <blk> [session_id]")
            session_id = int(rest[2]) if len(rest) > 2 else None
            cmd_dependency_remove(conn, rest[0], rest[1], session_id)
        elif subcmd == "dependency-list":
            if not rest:
                _cli_usage_error("Usage: shepherd dependency-list <item>")
            result = cmd_dependency_list(conn, rest[0])
            if result:
                print(result)
        elif subcmd == "dependency-enrich":
            cmd_dependency_enrich(conn)
        elif subcmd == "dep-classify":
            _cli_error(
                "Error: dep-classify has been removed. "
                "Use gate_point and satisfaction fields instead.",
                1,
            )
        else:
            _cli_usage_error(_USAGE)
    except LookupError as exc:
        _cli_error(f"Error: {exc}", 1)
    except ValueError as exc:
        code = 2 if "invalid" in str(exc).lower() or "must be" in str(exc).lower() else 1
        _cli_error(f"Error: {exc}", code)
    except RuntimeError as exc:
        _cli_error(f"Error: {exc}", 1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
