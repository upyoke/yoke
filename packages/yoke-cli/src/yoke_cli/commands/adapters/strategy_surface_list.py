"""Paged strategy corpus review read."""

from __future__ import annotations

import argparse

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.list_paging import add_page_args, dispatch_list
from yoke_cli.commands.adapters.strategy import strategy_target
from yoke_cli.commands.adapters.strategy_surfaces_usage import USAGE_BY_FUNCTION_ID


def strategy_surface_list(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke strategy surface list")
    add_project_arg(parser)
    add_page_args(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, USAGE_BY_FUNCTION_ID["strategy.surface.list"]
    )
    if parsed is None:
        return 2
    return dispatch_list(
        parsed=parsed,
        function_id="strategy.surface.list",
        target=strategy_target(parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
