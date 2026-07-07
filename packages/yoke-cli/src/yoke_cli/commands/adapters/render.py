"""``yoke agents render`` / ``yoke packets ...`` / ``yoke board data get``.

Four render-family flag adapters:

* ``agents.render.run`` — write the substrate agent prompts.
* ``agents.render.check`` — detect drift between rendered + canonical.
* ``packets.render.run`` — render a single LLM packet role.
* ``packets.check.run`` — verify packet rendering drift.
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
    "packets_render", "packets_check", "board_data_get",
    "AGENTS_RENDER_USAGE", "AGENTS_RENDER_CHECK_USAGE",
    "PACKETS_RENDER_USAGE", "PACKETS_CHECK_USAGE", "BOARD_DATA_GET_USAGE",
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
    add_session_arg(parser); add_json_arg(parser)
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
    add_session_arg(parser); add_json_arg(parser)
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
    add_session_arg(parser); add_json_arg(parser)
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
    add_session_arg(parser); add_json_arg(parser)
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


BOARD_DATA_GET_USAGE = (
    "yoke board data get [--scope NAME] [--session-id S] [--json]"
)


def board_data_get(args: List[str]) -> int:
    """Fetch the board's recorded data payload (operator-debug surface).

    The production consumer is the ``yoke board rebuild`` composition,
    which ships the checkout's board.json values and zen vision count;
    this bare adapter fetches the default-config plan for inspection.
    """
    parser = argparse.ArgumentParser(
        prog="yoke board data get", description=BOARD_DATA_GET_USAGE,
    )
    parser.add_argument("--scope", default="all",
                        help="Project scope (slug, id, or 'all').")
    add_session_arg(parser); add_json_arg(parser)
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
