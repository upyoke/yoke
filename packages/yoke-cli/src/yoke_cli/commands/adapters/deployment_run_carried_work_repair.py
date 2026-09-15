"""Flag adapter for re-deriving a run's unanswered carried-work record."""

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


DEPLOYMENT_RUNS_CARRIED_WORK_REPAIR_USAGE = (
    "yoke deployment-runs carried-work repair RUN-ID [--session-id S] [--json]"
)

_DESCRIPTION = """\
Re-derive the carried work of a run whose comparison never ran.

A run completed where its project's source could not be read stores a record
saying so, and that record is frozen like any other. This replaces exactly
that record, and only when a fresh derivation can answer it now: a record that
was actually derived is refused, and a second unanswerable derivation is
refused by the reason it failed rather than written as an empty release.
"""


def deployment_runs_carried_work_repair(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs carried-work repair",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=_DESCRIPTION,
    )
    parser.add_argument("run_id")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, DEPLOYMENT_RUNS_CARRIED_WORK_REPAIR_USAGE
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        derivation = (result.get("carried_work") or {}).get("derivation") or {}
        items = (result.get("carried_work") or {}).get("items") or []
        print(
            f"{result.get('run_id')} carried work re-derived from "
            f"{result.get('previous_reason') or 'an unanswered comparison'}: "
            f"{derivation.get('source') or 'unknown source'} resolved "
            f"{len(items)} item(s)",
            file=stdout,
        )
        return None

    return dispatch_and_emit(
        function_id="deployment_runs.carried_work.repair",
        target=TargetRef(kind="workflow_run", workflow_run_id=parsed.run_id),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "deployment_runs_carried_work_repair",
    "DEPLOYMENT_RUNS_CARRIED_WORK_REPAIR_USAGE",
]
