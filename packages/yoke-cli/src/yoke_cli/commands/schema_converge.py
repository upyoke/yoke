"""Source-dev/admin wrapper for additive core-schema convergence."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.config import machine_config
from yoke_contracts.machine_config.schema import ENV_OVERRIDE


AdapterFn = Callable[[List[str]], int]

SCHEMA_CONVERGE_USAGE = "yoke schema converge [--json]"

_DIRECT_AUTHORITY_ENV_VARS = ("YOKE_PG_DSN", "YOKE_PG_DSN_FILE")

_SCHEMA_CONVERGE_HELP = """\
Run the same idempotent, additive schema convergence used at API boot.
This creates missing tables, indexes, and additive columns; it does not
run seeds, destructive changes, data backfills, or the full init chain.

This is an explicit source-dev/admin operation. Database authority is
selected through the normal connected-environment contract, including
the global ``yoke --env NAME`` / ``YOKE_ENV`` override. A named environment
and a direct DSN override cannot be combined; the command fails closed rather
than risk converging a different database than the operator selected."""


def _failure(*, json_mode: bool, error_type: str) -> int:
    """Emit a secret-safe failure without echoing a DSN-bearing exception."""
    payload = {
        "error": "schema_convergence_failed",
        "error_type": error_type,
        "ok": False,
        "operation": "schema.converge",
    }
    if json_mode:
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
    else:
        print(
            "yoke schema converge failed "
            f"({error_type}); inspect the selected source-dev/admin "
            "environment with `yoke status --json`.",
            file=sys.stderr,
        )
    return 1


def _authority_conflict(
    *, json_mode: bool, environment: str, direct_variables: list[str],
) -> int:
    """Reject ambiguous named-environment plus direct-DSN authority."""
    payload = {
        "conflicting_environment_variables": direct_variables,
        "environment": environment,
        "error": "schema_authority_conflict",
        "ok": False,
        "operation": "schema.converge",
    }
    if json_mode:
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
    else:
        names = ", ".join(direct_variables)
        print(
            "yoke schema converge refused ambiguous database authority: "
            f"named environment {environment!r} conflicts with {names}. "
            "Unset the direct override or omit --env/YOKE_ENV.",
            file=sys.stderr,
        )
    return 1


def _authority_receipt() -> tuple[dict[str, str | None], list[str]]:
    """Return redacted authority identity and any unsafe override conflict."""
    environment = os.environ.get(ENV_OVERRIDE, "").strip()
    direct_variables = [
        name
        for name in _DIRECT_AUTHORITY_ENV_VARS
        if os.environ.get(name, "").strip()
    ]
    managed_secret = importlib.import_module(
        "yoke_core.domain.cloud_db_secret_dsn"
    )
    if managed_secret.env_binding_selected():
        direct_variables.append(managed_secret.DB_SECRET_ARN_ENV)
    if environment and direct_variables:
        return {"environment": environment}, direct_variables
    if direct_variables:
        if "YOKE_PG_DSN" in direct_variables:
            source = "direct_dsn"
        elif "YOKE_PG_DSN_FILE" in direct_variables:
            source = "direct_dsn_file"
        else:
            source = "managed_secret"
        return {
            "authority_source": source,
            "environment": None,
        }, []
    selected = machine_config.active_env(explicit_env=environment or None)
    return {
        "authority_source": "connected_environment",
        "environment": selected,
    }, []


def schema_converge(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke schema converge",
        description=(
            f"{SCHEMA_CONVERGE_USAGE}\n\n{_SCHEMA_CONVERGE_HELP}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Emit a machine-readable result.",
    )
    parsed = parse_or_usage_error(parser, args, SCHEMA_CONVERGE_USAGE)
    if parsed is None:
        return 2

    try:
        authority, direct_conflicts = _authority_receipt()
    except Exception as exc:  # noqa: BLE001 - CLI boundary redacts details
        return _failure(
            json_mode=parsed.json_mode,
            error_type=type(exc).__name__,
        )
    if direct_conflicts:
        return _authority_conflict(
            json_mode=parsed.json_mode,
            environment=str(authority["environment"]),
            direct_variables=direct_conflicts,
        )

    try:
        entrypoint = importlib.import_module(
            "yoke_core.api.server_entrypoint"
        )
    except ImportError:
        return _failure(json_mode=parsed.json_mode, error_type="ImportError")

    ensure_core_schema = getattr(entrypoint, "ensure_core_schema", None)
    if not callable(ensure_core_schema):
        return _failure(json_mode=parsed.json_mode, error_type="MissingEntrypoint")

    try:
        ensure_core_schema()
    except Exception as exc:  # noqa: BLE001 - CLI boundary redacts details
        return _failure(
            json_mode=parsed.json_mode,
            error_type=type(exc).__name__,
        )

    payload = {
        **authority,
        "ok": True,
        "operation": "schema.converge",
        "schema": "core",
    }
    if parsed.json_mode:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("Core schema converged.")
    return 0


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("schema", "converge"): schema_converge,
}

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke schema converge": SCHEMA_CONVERGE_USAGE,
}


__all__ = [
    "SCHEMA_CONVERGE_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "schema_converge",
]
