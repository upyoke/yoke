"""``yoke strategy seed-defaults`` adapter -> ``strategy.seed_defaults.run``.

Split from :mod:`yoke_cli.commands.adapters.strategy_render` (which owns
``render``/``ingest``) to respect the authored-file line cap; the three
commands share no state — each is a standalone dispatch.
"""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.strategy import strategy_target


__all__ = ["strategy_seed_defaults", "STRATEGY_SEED_DEFAULTS_USAGE"]


STRATEGY_SEED_DEFAULTS_USAGE = (
    "yoke strategy seed-defaults [--project P] [--session-id S] [--json]"
)


def strategy_seed_defaults(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy seed-defaults",
        description=(
            "Top up a project's default strategy docs: mint a placeholder "
            "row for each missing default slug (MISSION, VISION, "
            "MASTER-PLAN, LANDSCAPE, CURRENT-PLAN), parameterized by the "
            "project's display name. Idempotent per slug — existing rows "
            "are never touched, healing projects that predate a roster "
            "addition. Render files afterwards with `yoke strategy render`."
        ),
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_SEED_DEFAULTS_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        if result.get("already_seeded"):
            print(
                f"project {result.get('project_slug')} already carries all "
                f"{result.get('existing_rows')} default strategy doc(s); "
                "nothing seeded",
                file=stdout,
            )
            return
        print(
            f"seeded {', '.join(result.get('seeded', []))} for project "
            f"{result.get('project_slug')}",
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="strategy.seed_defaults.run",
        target=strategy_target(parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )
