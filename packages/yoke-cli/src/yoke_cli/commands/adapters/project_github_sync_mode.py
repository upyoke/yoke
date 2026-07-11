"""``yoke projects github-sync-mode repair`` adapter."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)


PROJECTS_GITHUB_SYNC_MODE_REPAIR_USAGE = (
    "yoke projects github-sync-mode repair [--project NAME] [--apply] [--json]"
)


def projects_github_sync_mode_repair(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects github-sync-mode repair",
        description=(
            "Find enabled (including legacy NULL) projects without an active, "
            "verified GitHub App binding, plus unbound projects with stale "
            "repository/capability projections. Dry-run unless --apply is "
            "supplied."
        ),
    )
    parser.add_argument("--project", default=None)
    parser.add_argument("--apply", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        PROJECTS_GITHUB_SYNC_MODE_REPAIR_USAGE,
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"apply": parsed.apply}
    if parsed.project:
        payload["project"] = parsed.project

    def _human_writer(response, stdout, stderr) -> None:
        if response.success:
            print(json.dumps(response.result or {}, sort_keys=True), file=stdout)
        return None

    return dispatch_and_emit(
        function_id="projects.github_sync_mode.repair",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "PROJECTS_GITHUB_SYNC_MODE_REPAIR_USAGE",
    "projects_github_sync_mode_repair",
]
