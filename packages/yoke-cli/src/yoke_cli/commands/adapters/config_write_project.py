"""Project checkout registration CLI adapter.

Split from :mod:`yoke_cli.commands.adapters.config_write` under the
authored-file line cap; re-exported there so existing imports are unaffected.
"""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.config_write_shared import run
from yoke_cli.config import writer

PROJECT_REGISTER_USAGE = (
    "yoke project register REPO_ROOT --project-id N "
    "[--board-scope SCOPE] [--board-render-path PATH] [--reassign] "
    "[--config PATH] [--json]"
)


def project_register(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke project register",
        description=(
            "Map one machine-local checkout to a project id, scoped to the selected connection.\n"
            "Moving a project id already routed elsewhere needs --reassign."
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Print the result as JSON.",
    )
    parser.add_argument(
        "repo_root", help="Path to the project checkout on this machine."
    )
    parser.add_argument(
        "--project-id",
        dest="project_id",
        type=int,
        required=True,
        help="Id of the project this checkout belongs to.",
    )
    parser.add_argument(
        "--board-scope",
        dest="board_scope",
        default=None,
        help="Board scope to record for this checkout.",
    )
    parser.add_argument(
        "--board-render-path",
        dest="board_render_path",
        default=None,
        help="Path where the board is rendered in this checkout.",
    )
    parser.add_argument(
        "--reassign",
        action="store_true",
        default=False,
        help=(
            "Deliberate checkout move; requires this session's live steering "
            "seat on the project."
        ),
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Machine config file to write; default: the usual config file.",
    )
    parsed = parse_or_usage_error(parser, args, PROJECT_REGISTER_USAGE)
    if parsed is None:
        return 2

    def _register() -> dict:
        return writer.register_project(
            parsed.repo_root,
            parsed.project_id,
            board_scope=parsed.board_scope,
            board_render_path=parsed.board_render_path,
            reassign=parsed.reassign,
            path=parsed.config_path,
        )

    import json
    import sys
    from yoke_cli.config.setup_facts_summary import read_project

    if parsed.json_mode:
        from yoke_cli.commands.adapters.config_write_shared import machine_config_errors

        try:
            result = _register()
        except machine_config_errors() as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        setup = read_project(
            parsed.repo_root, project=parsed.project_id, config_path=parsed.config_path
        )
        result["next_action"] = setup["next_action"]
        result["setup_summary"] = setup["lines"]
        print(json.dumps(result))
        return 0
    result_code = run(_register)
    if result_code == 0:
        setup = read_project(
            parsed.repo_root, project=parsed.project_id, config_path=parsed.config_path
        )
        print("\n".join(setup["lines"]), file=sys.stdout)
    return result_code


__all__ = ["PROJECT_REGISTER_USAGE", "project_register"]
