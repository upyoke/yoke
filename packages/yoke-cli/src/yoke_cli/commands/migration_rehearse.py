"""Source-dev/admin wrapper for governed migration rehearsal."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.config import machine_config
from yoke_contracts.control_plane_locality import local_authority_is_pinned
from yoke_contracts.machine_config.schema import ENV_OVERRIDE, TRANSPORT_HTTPS
from yoke_contracts.migration_rehearsal_teaching import (
    CONNECTION_READER,
    PREFLIGHT_HELP,
    PREFLIGHT_HELP_COMMAND,
)


AdapterFn = Callable[[List[str]], int]
MIGRATION_REHEARSE_USAGE = "yoke migration rehearse PREFIX-N"


def remote_without_admin_authority() -> bool:
    if local_authority_is_pinned():
        return False
    selected = os.environ.get(ENV_OVERRIDE, "").strip() or None
    connection = machine_config.active_connection(explicit_env=selected)
    return str(connection.get("transport") or "") == TRANSPORT_HTTPS


def migration_rehearse(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke migration rehearse",
        description=(
            "Rehearse one item-declared migration against its project-local "
            "validation surface. This is a source-dev/admin operation: use a "
            "local-Postgres or named db-admin connection, never an HTTPS "
            "product connection. Applying belongs to boot convergence."
        ),
        epilog=PREFLIGHT_HELP,
    )
    parser.add_argument(
        "item_ref", help="Public item reference, for example YOK-123"
    )
    parsed = parse_or_usage_error(parser, args, MIGRATION_REHEARSE_USAGE)
    if parsed is None:
        return 2

    try:
        if remote_without_admin_authority():
            selected = os.environ.get(ENV_OVERRIDE, "").strip() or "active HTTPS"
            print(
                "yoke migration rehearse refused: "
                f"{selected!r} has no local database authority; the rehearsal "
                "executes project-local code and is not relayed over HTTPS. "
                f"List the registered connections with `{CONNECTION_READER}`, "
                "then rerun under the local-Postgres or db-admin one whose "
                "universe holds the item: "
                "`yoke --env <name> migration rehearse ITEM`. Full preflight: "
                f"`{PREFLIGHT_HELP_COMMAND}`.",
                file=sys.stderr,
            )
            return 1
        module = importlib.import_module("yoke_core.domain.migration_apply")
        return int(module.main(["rehearse", parsed.item_ref]))
    except Exception as exc:  # noqa: BLE001 - redact authority details
        print(
            "yoke migration rehearse failed "
            f"({type(exc).__name__}); inspect the selected authority with "
            f"`yoke status --json` and the preflight with "
            f"`{PREFLIGHT_HELP_COMMAND}`.",
            file=sys.stderr,
        )
        return 1


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("migration", "rehearse"): migration_rehearse,
}

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke migration rehearse": MIGRATION_REHEARSE_USAGE,
}


__all__ = [
    "CONNECTION_READER",
    "MIGRATION_REHEARSE_USAGE",
    "PREFLIGHT_HELP",
    "PREFLIGHT_HELP_COMMAND",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "migration_rehearse",
    "remote_without_admin_authority",
]
