"""``yoke items dependency add|list|remove|update`` adapters."""

from __future__ import annotations

import argparse
from yoke_cli.commands.adapters.list_paging import add_page_args, dispatch_list

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
    "items_dependency_add",
    "items_dependency_list",
    "items_dependency_update",
    "items_dependency_remove",
    "ITEMS_DEPENDENCY_ADD_USAGE",
    "ITEMS_DEPENDENCY_LIST_USAGE",
    "ITEMS_DEPENDENCY_UPDATE_USAGE",
    "ITEMS_DEPENDENCY_REMOVE_USAGE",
]

ITEMS_DEPENDENCY_LIST_USAGE = (
    "yoke items dependency list (PREFIX-N | --item PREFIX-N) [--limit N] [--offset N] [--full] [--project P] "
    "[--session-id S] [--json]"
)


def items_dependency_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items dependency list",
        usage=ITEMS_DEPENDENCY_LIST_USAGE,
    )
    parser.add_argument(
        "--item",
        default=None,
        metavar="PREFIX-N",
        help="Item id (PREFIX-N). Alternative to positional.",
    )
    parser.add_argument(
        "item_positional",
        nargs="?",
        default=None,
        metavar="PREFIX-N",
        help="Item id (PREFIX-N). Alternative to --item.",
    )
    add_page_args(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_DEPENDENCY_LIST_USAGE)
    if parsed is None:
        return 2
    raw_item = parsed.item or parsed.item_positional
    if not raw_item:
        return usage_error(
            "items dependency list requires --item PREFIX-N or a positional item"
        )
    return dispatch_list(
        parsed=parsed,
        function_id="items.dependency.list",
        target=item_target("item", raw_item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


ITEMS_DEPENDENCY_ADD_USAGE = (
    "yoke items dependency add <dependent> <blocking> <source> "
    "[--gate-point activation|integration|closure|coordination_only] "
    "[--satisfaction status:<stage-id>|fact:merged|"
    "fact:deployed:<environment-name>] "
    "(--rationale TEXT | --rationale-file PATH) "
    "[--evidence JSON | --evidence-file PATH] [--project P] [--session-id S] [--json]"
)

_EXISTING_EDGE_HELP = """Existing edge:
  An add for a dependent, blocking item and gate point that already has an
  edge updates that edge in place: source and rationale always, satisfaction
  and evidence only when given. The reply names the dependency number and each
  changed field, or says "unchanged" when nothing differs.

"""

_SATISFACTION_HELP = """Satisfaction values:
  status:<stage-id> | fact:merged | fact:deployed:<environment-name>

Use the blocking item's pinned workflow stage for an item-to-item wait,
normally status:done when its required deployment and closeout must finish.
Any status:<stage-id> must exist in that workflow; authoring refuses an
unknown stage and lists the stages that workflow version has.

Use fact:merged when the dependent only needs the blocker's code on trunk,
including a fix that ships in the dependent's release or shared QA case.
Reserve fact:deployed:<environment-name> for a dependent that needs that code running
in a registered environment before its own release; a blocker shipping in that
same release cannot be delivered first, so composition skips the dependent. It requires the blocker at done with durable
completion delivery attribution to that environment, run and candidate, including
source-bound cross-project delivery. Merge or release status alone is insufficient.
Later sibling failure or cancellation does not erase completed attribution.
For failed delivery QA, see .yoke/docs/verification/failed-item-qa.md.
Add and update refuse an environment not registered for the blocking item's project.

Examples:
  yoke items dependency add APP-2 APP-1 operator --gate-point integration
    --satisfaction fact:merged --rationale "needs blocker on trunk"
  yoke items dependency add APP-3 APP-1 operator --gate-point activation
    --satisfaction fact:deployed:prod --rationale "acceptance uses the prod build"
  yoke items dependency add APP-4 APP-1 operator --gate-point activation
    --satisfaction status:reviewing-implementation --rationale "wait until review"
"""


def items_dependency_add(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items dependency add",
        usage=ITEMS_DEPENDENCY_ADD_USAGE,
        epilog=_EXISTING_EDGE_HELP + _SATISFACTION_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "item",
        metavar="dependent",
        help="Dependent item id (PREFIX-N).",
    )
    parser.add_argument(
        "blocking",
        help="Blocking item id (usually PREFIX-N).",
    )
    from yoke_contracts.dependency_values import VALID_GATE_POINTS, VALID_SOURCES

    parser.add_argument(
        "source", choices=sorted(VALID_SOURCES), help="Dependency source."
    )
    parser.add_argument(
        "--gate-point",
        choices=sorted(VALID_GATE_POINTS),
        default="activation",
        help="Point the edge blocks; default: activation.",
    )
    parser.add_argument(
        "--satisfaction",
        default=None,
        help="Condition grammar; see the values and examples below.",
    )
    rationale = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        rationale,
        "--rationale",
        "--rationale-file",
        dest="rationale",
        help_text="Non-empty authored rationale for the edge.",
    )
    evidence = parser.add_mutually_exclusive_group()
    add_text_file_pair(
        evidence,
        "--evidence",
        "--evidence-file",
        dest="evidence",
        help_text="JSON evidence payload (default {}).",
        file_help="Read JSON evidence payload from a file.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_DEPENDENCY_ADD_USAGE)
    if parsed is None:
        return 2
    try:
        rationale_text = resolve_text_file(
            parsed.rationale,
            parsed.rationale_file,
            "--rationale-file",
        )
        evidence_json = resolve_text_file(
            parsed.evidence,
            parsed.evidence_file,
            "--evidence-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))
    payload: Dict[str, Any] = {
        "blocking_item": parsed.blocking,
        "source": parsed.source,
        "gate_point": parsed.gate_point,
        "rationale": rationale_text,
    }
    if evidence_json:
        payload["evidence_json"] = evidence_json
    if parsed.satisfaction:
        payload["satisfaction"] = parsed.satisfaction
    return dispatch_and_emit(
        function_id="items.dependency.add",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


ITEMS_DEPENDENCY_UPDATE_USAGE = (
    "yoke items dependency update <dependent> <blocking> "
    "[--match-gate-point POINT] [--gate-point POINT] "
    "[--satisfaction status:<stage-id>|fact:merged|"
    "fact:deployed:<environment-name>] "
    "[--rationale TEXT | --rationale-file PATH] [--source SOURCE] "
    "[--evidence JSON | --evidence-file PATH] [--project P] [--session-id S] [--json]"
)


def items_dependency_update(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items dependency update",
        usage=ITEMS_DEPENDENCY_UPDATE_USAGE,
        epilog=_SATISFACTION_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "item",
        metavar="dependent",
        help="Dependent item id (PREFIX-N).",
    )
    parser.add_argument("blocking", help="Blocking item id (usually PREFIX-N).")
    parser.add_argument(
        "--match-gate-point",
        default=None,
        metavar="POINT",
        help="Gate point of the edge to update.",
    )
    parser.add_argument(
        "--gate-point",
        default=None,
        metavar="POINT",
        help="New gate point for the edge.",
    )
    parser.add_argument(
        "--satisfaction",
        default=None,
        help="Condition grammar; deployed environments must be registered.",
    )
    rationale = parser.add_mutually_exclusive_group()
    add_text_file_pair(
        rationale,
        "--rationale",
        "--rationale-file",
        dest="rationale",
        help_text="Updated rationale text.",
    )
    from yoke_contracts.dependency_values import VALID_SOURCES

    parser.add_argument(
        "--source",
        choices=sorted(VALID_SOURCES),
        default=None,
        help="New dependency source.",
    )
    evidence = parser.add_mutually_exclusive_group()
    add_text_file_pair(
        evidence,
        "--evidence",
        "--evidence-file",
        dest="evidence",
        help_text="Replacement JSON evidence payload.",
        file_help="Read replacement JSON evidence payload from a file.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_DEPENDENCY_UPDATE_USAGE)
    if parsed is None:
        return 2
    try:
        rationale_text = resolve_text_file(
            parsed.rationale,
            parsed.rationale_file,
            "--rationale-file",
        )
        evidence_json = resolve_text_file(
            parsed.evidence,
            parsed.evidence_file,
            "--evidence-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))
    payload: Dict[str, Any] = {"blocking_item": parsed.blocking}
    for key in ("match_gate_point", "gate_point", "satisfaction", "source"):
        value = getattr(parsed, key)
        if value:
            payload[key] = value
    if rationale_text:
        payload["rationale"] = rationale_text
    if evidence_json:
        payload["evidence_json"] = evidence_json
    return dispatch_and_emit(
        function_id="items.dependency.update",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


ITEMS_DEPENDENCY_REMOVE_USAGE = (
    "yoke items dependency remove <dependent> <blocking> [--project P] "
    "[--session-id S] [--json]"
)


def items_dependency_remove(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items dependency remove",
        usage=ITEMS_DEPENDENCY_REMOVE_USAGE,
    )
    parser.add_argument(
        "item",
        metavar="dependent",
        help="Dependent item id (PREFIX-N).",
    )
    parser.add_argument("blocking", help="Blocking item id (usually PREFIX-N).")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_DEPENDENCY_REMOVE_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="items.dependency.remove",
        target=item_target("item", parsed.item, parsed.project),
        payload={"blocking_item": parsed.blocking},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
