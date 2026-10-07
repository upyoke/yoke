"""``yoke local demo seed``: a few demo backlog items in a non-prod local universe.

The engine half is :mod:`yoke_core.domain.local_demo_seed`, imported
dynamically like every client-side engine seam; this module parses the
command and refuses any connection that is not a non-prod local-postgres one.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import Any, Dict, List

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.config import local_universe_setup as setup

DEMO_SEED_USAGE = (
    "yoke local demo seed [--project PROJECT] [--count N] [--config PATH] [--json]"
)


def local_demo_seed(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke local demo seed",
        description=(
            "Seed a non-prod local universe with a few demo backlog items "
            "for installer smoke tests."
        ),
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project slug or id; defaults to the checkout's configured project.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="Number of smoke items to create (default: 3).",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Machine config path override.",
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, DEMO_SEED_USAGE)
    if parsed is None:
        return 2
    if parsed.count < 1:
        print("error: --count must be at least 1", file=sys.stderr)
        return 2
    try:
        report = _seed_demo_items(
            project=parsed.project,
            count=parsed.count,
            config_path=parsed.config_path,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for item in report.get("items", []):
            print(f"{item.get('public_ref')}: {item.get('title')}")
        print(
            report.get(
                "next_step",
                "run `yoke board rebuild --print --no-pager`",
            )
        )
    return 0


def _seed_demo_items(
    *,
    project: str | None,
    count: int,
    config_path: str | None,
) -> Dict[str, Any]:
    from yoke_cli.config import machine_config
    from yoke_cli.project_install.transport import _local_postgres_env
    from yoke_contracts.machine_config import schema as contract

    try:
        connection = machine_config.active_connection(config_path)
    except contract.MachineConfigContractError as exc:
        raise setup.LocalUniverseSetupError(str(exc)) from exc
    transport = str(connection.get("transport") or "").strip()
    env_name = str(connection.get("env") or "<env>")
    if transport not in contract.POSTGRES_TRANSPORTS:
        raise setup.LocalUniverseSetupError(
            f"env {env_name!r} is {transport or 'unconfigured'}, not local-postgres"
        )
    if contract.connection_is_prod(connection):
        raise setup.LocalUniverseSetupError(
            f"env {env_name!r} is prod-marked; demo seeding is local-only"
        )
    try:
        db_backend = importlib.import_module("yoke_core.domain.db_backend")
        seed_demo_items = importlib.import_module(
            "yoke_core.domain.local_demo_seed"
        ).seed_demo_items
    except ModuleNotFoundError as exc:
        raise setup.LocalUniverseSetupError(
            "the yoke-core engine package is not importable; reinstall Yoke"
        ) from exc
    with _local_postgres_env(
        connection,
        config_path,
        dsn_env=db_backend.PG_DSN_ENV,
        dsn_file_env=db_backend.PG_DSN_FILE_ENV,
    ):
        return seed_demo_items(project=project, count=count)


__all__ = ["DEMO_SEED_USAGE", "local_demo_seed"]
