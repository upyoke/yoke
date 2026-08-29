"""CLI adapters for strategy review and Blitz document execution."""

from __future__ import annotations

import argparse
from typing import Callable, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.strategy import strategy_target
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.public_ref import parse_public_item_ref
from yoke_contracts.work_processes import is_known_process, list_processes


def _global(
    args: List[str],
    *,
    tokens: str,
    configure: Callable[[argparse.ArgumentParser], None] | None,
    function_id: str,
    payload: Callable[[argparse.Namespace], dict],
) -> int:
    usage = f"yoke {tokens} [--project P] [--json]"
    parser = argparse.ArgumentParser(prog=f"yoke {tokens}", description=usage)
    if configure is not None:
        configure(parser)
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id=function_id,
        target=strategy_target(parsed.project),
        payload=payload(parsed),
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def strategy_surface_list(args: List[str]) -> int:
    return _global(
        args, tokens="strategy surface list", configure=None,
        function_id="strategy.surface.list", payload=lambda _parsed: {},
    )


def strategy_surface_get(args: List[str]) -> int:
    return _global(
        args, tokens="strategy surface get",
        configure=lambda parser: parser.add_argument("slug"),
        function_id="strategy.surface.get",
        payload=lambda parsed: {"slug": parsed.slug},
    )


def _diff_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug")
    parser.add_argument("--from-revision", type=int, required=True)
    parser.add_argument("--to-revision", type=int, required=True)


def strategy_revision_diff(args: List[str]) -> int:
    return _global(
        args, tokens="strategy revision diff", configure=_diff_args,
        function_id="strategy.revision.diff",
        payload=lambda parsed: {
            "slug": parsed.slug,
            "from_revision": parsed.from_revision,
            "to_revision": parsed.to_revision,
        },
    )


def _restore_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug")
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--base-updated-at", required=True)


def strategy_revision_restore(args: List[str]) -> int:
    return _global(
        args, tokens="strategy revision restore", configure=_restore_args,
        function_id="strategy.revision.restore",
        payload=lambda parsed: {
            "slug": parsed.slug,
            "revision": parsed.revision,
            "base_updated_at": parsed.base_updated_at,
        },
    )


def _parent_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug")
    parent = parser.add_mutually_exclusive_group(required=True)
    parent.add_argument("--parent-slug")
    parent.add_argument("--clear", action="store_true")


def strategy_parent_set(args: List[str]) -> int:
    return _global(
        args, tokens="strategy parent set", configure=_parent_args,
        function_id="strategy.parent.set",
        payload=lambda parsed: {
            "slug": parsed.slug,
            "parent_slug": None if parsed.clear else parsed.parent_slug,
        },
    )


def _coordination_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug")
    parser.add_argument("--section", required=True)
    parser.add_argument("--entry", required=True)


def strategy_coordination_append(args: List[str]) -> int:
    return _global(
        args, tokens="strategy coordination append",
        configure=_coordination_args,
        function_id="strategy.coordination.append",
        payload=lambda parsed: {
            "slug": parsed.slug,
            "section": parsed.section,
            "entry": parsed.entry,
        },
    )


def _item(
    args: List[str],
    *,
    tokens: str,
    function_id: str,
    configure: Callable[[argparse.ArgumentParser], None] | None = None,
    payload: Callable[[argparse.Namespace], dict] = lambda _parsed: {},
) -> int:
    usage = f"yoke {tokens} ITEM [--project P] [--json]"
    parser = argparse.ArgumentParser(prog=f"yoke {tokens}", description=usage)
    parser.add_argument("item")
    parser.add_argument("--project")
    if configure is not None:
        configure(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id=function_id,
        target=item_target("item", parsed.item, parsed.project),
        payload=payload(parsed),
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def strategy_execution_get(args: List[str]) -> int:
    return _item(
        args, tokens="strategy execution get",
        function_id="strategy.execution.get",
    )


def strategy_execution_link(args: List[str]) -> int:
    return _item(
        args, tokens="strategy execution link",
        function_id="strategy.execution.link",
        configure=lambda parser: parser.add_argument("--slug", required=True),
        payload=lambda parsed: {"slug": parsed.slug},
    )


def strategy_claim_acquire(args: List[str]) -> int:
    return _item(
        args, tokens="strategy claim acquire",
        function_id="strategy.claim.acquire",
    )


def strategy_claim_release(args: List[str]) -> int:
    """Release a Blitz document claim (ITEM) or a process claim (KEY).

    Process keys (STRATEGIZE / FEED / DOCTOR) route to
    ``claims.work.release`` so era closeout can run
    ``yoke strategy claim release STRATEGIZE`` without a claim id.
    """
    usage = (
        "yoke strategy claim release (ITEM | PROCESS_KEY) "
        "[--reason TEXT] [--project P] [--json]\n"
        "  ITEM releases the Blitz document claim on that item.\n"
        "  PROCESS_KEY (STRATEGIZE, FEED, DOCTOR) releases this "
        "session's process claim via claims.work.release.\n"
        "  Equivalent process form: yoke claims work release "
        "--process KEY --reason TEXT"
    )
    parser = argparse.ArgumentParser(
        prog="yoke strategy claim release", description=usage,
    )
    parser.add_argument("item")
    parser.add_argument("--project")
    parser.add_argument("--reason")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2

    raw = str(parsed.item).strip()
    key = raw.upper()
    if is_known_process(key):
        project = parsed.project or client_project_context(None) or "yoke"
        return dispatch_and_emit(
            function_id="claims.work.release",
            target=TargetRef(kind="global", project_id=project),
            payload={
                "reason": parsed.reason or "released",
                "process_key": key,
                "project": project,
            },
            session_id=parsed.session_id,
            json_mode=parsed.json_mode,
        )
    # Non-item-shaped tokens (e.g. CURRENT-PLAN) get a process-key hint
    # instead of the opaque public_ref_unresolved dispatcher error.
    _, item_sequence = parse_public_item_ref(raw)
    looks_like_item = item_sequence is not None
    if not looks_like_item:
        known = ", ".join(list_processes())
        print(
            f"unknown process key {raw!r}; known keys: [{known}]. "
            "Pass a PREFIX-N item ref to release a Blitz document claim, "
            "or: yoke claims work release --process KEY --reason TEXT",
            flush=True,
        )
        return 2

    return dispatch_and_emit(
        function_id="strategy.claim.release",
        target=item_target("item", parsed.item, parsed.project),
        payload={"reason": parsed.reason},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def strategy_claim_break_glass_release(args: List[str]) -> int:
    return _item(
        args, tokens="strategy claim break-glass-release",
        function_id="strategy.claim.break_glass_release",
        configure=lambda parser: parser.add_argument("--reason", required=True),
        payload=lambda parsed: {"reason": parsed.reason},
    )


def _doc_claim_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug")
    parser.add_argument("--reason")


def strategy_doc_claim_acquire(args: List[str]) -> int:
    return _global(
        args, tokens="strategy doc-claim acquire", configure=_doc_claim_args,
        function_id="strategy.doc_claim.acquire",
        payload=lambda parsed: {"slug": parsed.slug, "reason": parsed.reason},
    )


def strategy_doc_claim_release(args: List[str]) -> int:
    return _global(
        args, tokens="strategy doc-claim release", configure=_doc_claim_args,
        function_id="strategy.doc_claim.release",
        payload=lambda parsed: {"slug": parsed.slug, "reason": parsed.reason},
    )


def strategy_doc_claim_list(args: List[str]) -> int:
    return _global(
        args, tokens="strategy doc-claim list",
        configure=lambda parser: parser.add_argument(
            "--all", dest="include_released", action="store_true",
            help="Include released claims, not only the live holders.",
        ),
        function_id="strategy.doc_claim.list",
        payload=lambda parsed: {"active_only": not parsed.include_released},
    )


USAGE_BY_FUNCTION_ID = {
    "strategy.surface.list": "yoke strategy surface list --project P",
    "strategy.surface.get": "yoke strategy surface get SLUG --project P",
    "strategy.revision.diff": "yoke strategy revision diff SLUG --from-revision N --to-revision N --project P",
    "strategy.revision.restore": "yoke strategy revision restore SLUG --revision N --base-updated-at TS --project P",
    "strategy.parent.set": "yoke strategy parent set SLUG --parent-slug PARENT --project P",
    "strategy.coordination.append": "yoke strategy coordination append SLUG --section NAME --entry TEXT --project P",
    "strategy.execution.get": "yoke strategy execution get ITEM --project P",
    "strategy.execution.link": "yoke strategy execution link ITEM --slug SLUG --project P",
    "strategy.claim.acquire": "yoke strategy claim acquire ITEM --project P",
    "strategy.claim.release": (
        "yoke strategy claim release (ITEM | PROCESS_KEY) "
        "[--reason TEXT] --project P"
    ),
    "strategy.claim.break_glass_release": "yoke strategy claim break-glass-release ITEM --reason TEXT --project P",
    "strategy.doc_claim.acquire": (
        "yoke strategy doc-claim acquire SLUG [--reason TEXT] --project P"
    ),
    "strategy.doc_claim.release": (
        "yoke strategy doc-claim release SLUG [--reason TEXT] --project P"
    ),
    "strategy.doc_claim.list": "yoke strategy doc-claim list [--all] --project P",
}


__all__ = ["USAGE_BY_FUNCTION_ID"] + [
    name for name in globals() if name.startswith("strategy_")
]
