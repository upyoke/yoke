"""``yoke shepherd dependency-*`` write adapters."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file


__all__ = [
    "shepherd_dependency_add",
    "shepherd_dependency_update",
    "shepherd_dependency_remove",
    "SHEPHERD_DEPENDENCY_ADD_USAGE",
    "SHEPHERD_DEPENDENCY_UPDATE_USAGE",
    "SHEPHERD_DEPENDENCY_REMOVE_USAGE",
]


SHEPHERD_DEPENDENCY_ADD_USAGE = (
    "yoke shepherd dependency-add <dependent> <blocking> <source> "
    "[--gate-point activation|integration|closure|coordination_only] "
    "[--satisfaction status:done|status:implemented|fact:merged] "
    "(--rationale TEXT | --rationale-file PATH) "
    "[--evidence JSON | --evidence-file PATH] [--session-id S] [--json]"
)


def shepherd_dependency_add(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke shepherd dependency-add",
        description=SHEPHERD_DEPENDENCY_ADD_USAGE,
    )
    parser.add_argument(
        "item", metavar="dependent",
        help="Dependent item id (PREFIX-N or project-local number).",
    )
    parser.add_argument(
        "blocking", help="Blocking item id (usually PREFIX-N).",
    )
    parser.add_argument(
        "source",
        help="Dependency source: conduct, feed, idea, migration, operator, refine, shepherd.",
    )
    parser.add_argument("--gate-point", default="activation")
    parser.add_argument("--satisfaction", default=None)
    rationale = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        rationale, "--rationale", "--rationale-file",
        dest="rationale",
        help_text="Non-empty authored rationale for the edge.",
    )
    evidence = parser.add_mutually_exclusive_group()
    add_text_file_pair(
        evidence, "--evidence", "--evidence-file",
        dest="evidence",
        help_text="JSON evidence payload (default {}).",
        file_help="Read JSON evidence payload from a file.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SHEPHERD_DEPENDENCY_ADD_USAGE)
    if parsed is None:
        return 2
    try:
        rationale_text = resolve_text_file(
            parsed.rationale, parsed.rationale_file, "--rationale-file",
        )
        evidence_json = resolve_text_file(
            parsed.evidence, parsed.evidence_file, "--evidence-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))
    payload: Dict[str, Any] = {
        "blocking_item": parsed.blocking,
        "source": parsed.source,
        "gate_point": parsed.gate_point,
        "rationale": rationale_text,
        "evidence_json": evidence_json or "{}",
    }
    if parsed.satisfaction:
        payload["satisfaction"] = parsed.satisfaction
    return dispatch_and_emit(
        function_id="shepherd.dependency_add.run",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


SHEPHERD_DEPENDENCY_UPDATE_USAGE = (
    "yoke shepherd dependency-update <dependent> <blocking> "
    "[--match-gate-point POINT] [--gate-point POINT] "
    "[--satisfaction VALUE] [--rationale TEXT | --rationale-file PATH] "
    "[--session-id S] [--json]"
)


def shepherd_dependency_update(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke shepherd dependency-update",
        description=SHEPHERD_DEPENDENCY_UPDATE_USAGE,
    )
    parser.add_argument(
        "item", metavar="dependent",
        help="Dependent item id (PREFIX-N or project-local number).",
    )
    parser.add_argument("blocking", help="Blocking item id (usually PREFIX-N).")
    parser.add_argument("--match-gate-point", default=None)
    parser.add_argument("--gate-point", default=None)
    parser.add_argument("--satisfaction", default=None)
    rationale = parser.add_mutually_exclusive_group()
    add_text_file_pair(
        rationale, "--rationale", "--rationale-file",
        dest="rationale",
        help_text="Updated rationale text.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SHEPHERD_DEPENDENCY_UPDATE_USAGE)
    if parsed is None:
        return 2
    try:
        rationale_text = resolve_text_file(
            parsed.rationale, parsed.rationale_file, "--rationale-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))
    payload: Dict[str, Any] = {"blocking_item": parsed.blocking}
    for source_key, payload_key in (
        ("match_gate_point", "match_gate_point"),
        ("gate_point", "gate_point"),
        ("satisfaction", "satisfaction"),
    ):
        value = getattr(parsed, source_key)
        if value:
            payload[payload_key] = value
    if rationale_text:
        payload["rationale"] = rationale_text
    return dispatch_and_emit(
        function_id="shepherd.dependency_update.run",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


SHEPHERD_DEPENDENCY_REMOVE_USAGE = (
    "yoke shepherd dependency-remove <dependent> <blocking> "
    "[--session-id S] [--json]"
)


def shepherd_dependency_remove(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke shepherd dependency-remove",
        description=SHEPHERD_DEPENDENCY_REMOVE_USAGE,
    )
    parser.add_argument(
        "item", metavar="dependent",
        help="Dependent item id (PREFIX-N or project-local number).",
    )
    parser.add_argument("blocking", help="Blocking item id (usually PREFIX-N).")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SHEPHERD_DEPENDENCY_REMOVE_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="shepherd.dependency_remove.run",
        target=item_target("item", parsed.item, parsed.project),
        payload={"blocking_item": parsed.blocking},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
