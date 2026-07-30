"""CLI adapter for faithful deployment-run snapshot projection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)


USAGE = (
    "yoke deployment-runs project-snapshot --snapshot-file PATH "
    "[--expected-destination-digest DIGEST] [--session-id S] [--json]"
)


def deployment_runs_project_snapshot(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs project-snapshot",
        description=USAGE,
    )
    parser.add_argument("--snapshot-file", required=True)
    parser.add_argument("--expected-destination-digest", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, USAGE)
    if parsed is None:
        return 2
    try:
        snapshot = json.loads(
            Path(parsed.snapshot_file).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"snapshot file is unreadable or invalid JSON: {exc}")
    if not isinstance(snapshot, dict):
        parser.error("snapshot file must contain one JSON object")
    payload = {"snapshot": snapshot}
    if parsed.expected_destination_digest is not None:
        payload["expected_destination_digest"] = (
            parsed.expected_destination_digest
        )
    return dispatch_and_emit(
        function_id="deployment_runs.project_snapshot",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = ["USAGE", "deployment_runs_project_snapshot"]
