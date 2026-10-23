"""Machine-local cleanup of Yoke-owned settings for deleted lanes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from yoke_cli.config.machine_config import all_registered_checkouts
from yoke_contracts.harness_lane_cleanup import (
    SWEEP_COMMAND,
    cleanup_lane_configs,
    managed_lane_roots,
)

USAGE = f"{SWEEP_COMMAND} [--managed-root PATH ...] [--dry-run] [--json]"


def sweep(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=SWEEP_COMMAND,
        description="Remove path-owned state for missing lanes across all harnesses. "
        "Back up each changed configuration beside it before writing; "
        "preserve live paths and every path outside managed roots.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report without writing configs or backups.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="Print the result as JSON.",
    )
    parser.add_argument(
        "--managed-root",
        type=Path,
        action="append",
        default=[],
        help="Additional root reserved for Yoke lanes or QA fixtures (repeatable).",
    )
    parsed = parser.parse_args(args)
    try:
        checkouts = tuple(all_registered_checkouts(existing_only=False))
        additional_roots = tuple(path.expanduser() for path in parsed.managed_root)
        for root in additional_roots:
            if not root.is_absolute() or root.resolve() in (
                Path("/"),
                Path.home(),
                Path("/tmp").resolve(),
            ):
                raise ValueError(
                    "harness_lane_config_root_invalid: name an absolute directory reserved for Yoke lanes or QA fixtures"
                )
        receipt = cleanup_lane_configs(
            managed_roots=managed_lane_roots(checkouts) + additional_roots,
            dry_run=parsed.dry_run,
            keep_backup=True,
        )
    except Exception as exc:
        receipt = dict(
            ok=False,
            dry_run=parsed.dry_run,
            files=[
                dict(
                    error="harness_lane_config_cleanup_failed",
                    detail=str(exc),
                    recovery="Repair the named inventory or root, then rerun the same sweep.",
                )
            ],
        )
    if parsed.json_mode:
        print(json.dumps(receipt, sort_keys=True))
    else:
        print(
            "Harness lane config cleanup preview:"
            if parsed.dry_run
            else "Harness lane config cleanup:"
        )
        for row in receipt["files"]:
            if "error" in row:
                print(f"{row['error']}: {row['detail']}. {row['recovery']}")
            else:
                print(
                    f"{row['harness']}: {row['file']}: removed {row['removed']}; "
                    f"bytes {row['before_bytes']} -> "
                    f"{row['after_bytes']}; backup {row['backup'] or 'none'}"
                )
    return 0 if receipt["ok"] else 1


TOOL_SHAPED_SUBCOMMANDS = {("harness", "lane-config", "sweep"): sweep}
TOOL_SHAPED_USAGE = {SWEEP_COMMAND: USAGE}
