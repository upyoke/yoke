"""Project-mapping CLI adapters: ``yoke project register`` / ``yoke config
stamp-project-env``.

Split from :mod:`yoke_cli.commands.adapters.config_write` under the
authored-file line cap; re-exported there so existing imports are unaffected.
"""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import attach_field_note_footer, parse_or_usage_error
from yoke_cli.commands.adapters.config_write_shared import run
from yoke_cli.config import writer

PROJECT_REGISTER_USAGE = (
    "yoke project register REPO_ROOT --project-id N "
    "[--board-scope SCOPE] [--board-render-path PATH] [--reassign] "
    "[--config PATH]"
)
STAMP_PROJECT_ENV_USAGE = "yoke config stamp-project-env [--config PATH]"


def project_register(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke project register", description=(
            "Map a checkout to a project id for ONE connection env. Project\n"
            "ids are per universe, so the row is recorded against the\n"
            "selected env (--env / YOKE_ENV / active_env) and resolves\n"
            "under no other; register once per env, other rows intact.\n"
            "Moving a project id already routed elsewhere needs --reassign."
        ),
    )
    parser.add_argument("repo_root")
    parser.add_argument("--project-id", dest="project_id", type=int, required=True)
    parser.add_argument("--board-scope", dest="board_scope", default=None)
    parser.add_argument("--board-render-path", dest="board_render_path",
                        default=None)
    parser.add_argument(
        "--reassign", action="store_true", default=False,
        help="Deliberate setup/operator-authorized checkout move only.",
    )
    parser.add_argument("--config", dest="config_path", default=None)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, PROJECT_REGISTER_USAGE)
    if parsed is None:
        return 2
    return run(lambda: writer.register_project(
        parsed.repo_root,
        parsed.project_id,
        board_scope=parsed.board_scope,
        board_render_path=parsed.board_render_path,
        reassign=parsed.reassign,
        path=parsed.config_path,
    ))


def config_stamp_project_env(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke config stamp-project-env",
        description=(
            "Stamp every untagged projects entry with the connection env its "
            "project_id belongs to. Defaults to the active env; select another "
            "with the global env flag (e.g. `yoke --env prod config "
            "stamp-project-env`). Already-tagged entries are left untouched."
        ),
    )
    parser.add_argument("--config", dest="config_path", default=None)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, STAMP_PROJECT_ENV_USAGE)
    if parsed is None:
        return 2
    # env is None here so the writer resolves it from the connection env the
    # invocation selected (global --env / YOKE_ENV, else active_env).
    return run(lambda: writer.stamp_untagged_project_envs(
        path=parsed.config_path,
    ))


__all__ = [
    "PROJECT_REGISTER_USAGE",
    "STAMP_PROJECT_ENV_USAGE",
    "config_stamp_project_env",
    "project_register",
]
