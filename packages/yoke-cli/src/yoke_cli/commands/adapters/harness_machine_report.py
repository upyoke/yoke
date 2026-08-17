"""``yoke harness machine-report upsert`` flag adapter."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


HARNESS_MACHINE_REPORT_UPSERT_USAGE = (
    "yoke harness machine-report upsert --project-id N "
    "[--repo-root PATH] [--session-id S] [--json]"
)
USAGE_BY_FUNCTION_ID = {
    "harness.machine_report.upsert": HARNESS_MACHINE_REPORT_UPSERT_USAGE,
}


def harness_machine_report_upsert(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke harness machine-report upsert",
        description=HARNESS_MACHINE_REPORT_UPSERT_USAGE,
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--repo-root", default=".")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, HARNESS_MACHINE_REPORT_UPSERT_USAGE)
    if parsed is None:
        return 2
    from yoke_cli.project_install.harness_inventory import collect_harness_inventory

    reports = collect_harness_inventory(Path(parsed.repo_root))
    return dispatch_and_emit(
        function_id="harness.machine_report.upsert",
        target=TargetRef(kind="global"),
        payload={"project_id": parsed.project_id, "reports": reports},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "HARNESS_MACHINE_REPORT_UPSERT_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "harness_machine_report_upsert",
]
