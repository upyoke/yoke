"""CLI adapter for the typed Pulumi state migration."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


PULUMI_STATE_MIGRATE_USAGE = (
    "yoke projects pulumi-state migrate --project NAME --site-id ID "
    "--stack NAME [--stack NAME ...] [--apply] [--json]"
)


def projects_pulumi_state_migrate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects pulumi-state migrate",
        description=(
            "Move one exact set of Pulumi operator-state entries from a site "
            "to the project capability. Dry-runs by default and never emits "
            "the migrated values."
        ),
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--stack", dest="stack_names", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PULUMI_STATE_MIGRATE_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        stdout.write(
            f"{result.get('mode', '')}|{result.get('receipt_digest', '')}\n"
        )

    return dispatch_and_emit(
        function_id="projects.pulumi_state.migrate",
        target=TargetRef(kind="global"),
        payload={
            "project": parsed.project,
            "site_id": parsed.site_id,
            "stack_names": parsed.stack_names,
            "apply": parsed.apply,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["PULUMI_STATE_MIGRATE_USAGE", "projects_pulumi_state_migrate"]
