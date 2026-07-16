"""Tool-shaped ``yoke init`` / ``yoke local-postgres`` / ``yoke universe``
commands.

Client-local machine operations with NO dispatcher function id: they
create and manage the machine's own universe, so there is no control
plane to dispatch through until they have run. Like the other tool-shaped
families they resolve via the tool-shaped table after SUBCOMMAND_REGISTRY
misses.

``yoke init --local`` is the birth path for local mode: embedded Postgres
fetched lazily and started under ``~/.yoke/``, control-plane schema
bootstrapped, org identity card and the one human actor ensured, and the
machine config pointed at the new universe. ``yoke local-postgres
start|stop|status`` manage the embedded server on its own. ``yoke
universe export`` dumps the universe database to one self-contained
portable archive (a tar carrying the database dump and its freeze
receipt) — the leave/graduate half of dump-and-restore between
deployment modes.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import Any, Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.config import local_universe_setup as setup

AdapterFn = Callable[[List[str]], int]

INIT_USAGE = (
    "yoke init --local [--org-name NAME] [--force] [--config PATH] [--json]"
)

EXPORT_USAGE = "yoke universe export [--out PATH] [--json]"
DEMO_SEED_USAGE = (
    "yoke local demo seed [--project PROJECT] [--count N] [--config PATH] [--json]"
)

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke init": INIT_USAGE,
    "yoke local demo seed": DEMO_SEED_USAGE,
    "yoke local-postgres start": "yoke local-postgres start [--json]",
    "yoke local-postgres stop": "yoke local-postgres stop [--json]",
    "yoke local-postgres status": "yoke local-postgres status [--json]",
    "yoke universe export": EXPORT_USAGE,
}


def init(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke init",
        description=(
            "Create a machine-local Yoke universe: embedded Postgres under "
            "~/.yoke/, full control-plane schema, org identity card, one "
            "human actor, and a 'local' machine-config connection. Free, "
            "no signup; all state stays on this machine."
        ),
    )
    parser.add_argument(
        "--local", action="store_true",
        help="Explicit mode selector: the machine-local embedded universe.",
    )
    parser.add_argument(
        "--org-name", dest="org_name", default=None,
        help="Name for the org identity card (default keeps the existing one).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Replace a conflicting existing 'local' machine-config connection.",
    )
    parser.add_argument("--config", dest="config_path", default=None,
                        help="Machine config path override.")
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, INIT_USAGE)
    if parsed is None:
        return 2
    if not parsed.local:
        print(
            "error: yoke init requires an explicit mode; today that is "
            f"--local. Usage: {INIT_USAGE}",
            file=sys.stderr,
        )
        return 2
    emit = _emit_for(parsed.json_mode)
    try:
        report = setup.run_local_init(
            org_name=parsed.org_name,
            force=parsed.force,
            config_path=parsed.config_path,
            emit=emit,
        )
    except setup.LocalUniverseSetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_init_summary(report)
    return 0


def universe_export(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke universe export",
        description=(
            "Export the active universe's database to one self-contained "
            "portable archive: a tar carrying the pg_dump payload and the "
            "freeze receipt that binds it, so the importer verifies the "
            "file by itself — the leave/graduate half of moving a universe "
            "between deployment modes. Requires holding the database DSN: "
            "sanctioned for a non-prod local-postgres connection. An https "
            "connection refuses because this machine holds no DSN: hosted "
            "org admins use the dashboard's Move universe action, while a "
            "self-host operator owns the server backup authority. "
            "Prod-flagged Postgres connections stay operator-only."
        ),
    )
    parser.add_argument(
        "--out", default=None,
        help=(
            "Output file or directory; a trailing / always means a "
            "directory (created when missing). Default: "
            "<org-slug>-universe-<utc-timestamp>.tar in the current "
            "directory."
        ),
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, EXPORT_USAGE)
    if parsed is None:
        return 2
    emit = _emit_for(parsed.json_mode)
    try:
        report = setup.universe_export(out=parsed.out, emit=emit)
    except setup.LocalUniverseSetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"universe export: {report.get('artifact')}")
        print(f"org: {report.get('org')}")
        print(f"format: {report.get('format')} bytes: {report.get('bytes')}")
    return 0


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
    parser.add_argument("--config", dest="config_path", default=None,
                        help="Machine config path override.")
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
            print(f"{item.get('item_ref')}: {item.get('title')}")
        print(report.get(
            "next_step",
            "run `yoke board rebuild --print --no-pager`",
        ))
    return 0


def local_postgres_start(args: List[str]) -> int:
    parsed = _lifecycle_parse("start", args)
    if parsed is None:
        return 2
    return _lifecycle_run(
        lambda: setup.postgres_start(emit=_emit_for(parsed.json_mode)),
        parsed.json_mode,
    )


def local_postgres_stop(args: List[str]) -> int:
    parsed = _lifecycle_parse("stop", args)
    if parsed is None:
        return 2
    return _lifecycle_run(setup.postgres_stop, parsed.json_mode)


def local_postgres_status(args: List[str]) -> int:
    parsed = _lifecycle_parse("status", args)
    if parsed is None:
        return 2
    return _lifecycle_run(setup.postgres_status, parsed.json_mode)


def _lifecycle_parse(verb: str, args: List[str]):
    parser = argparse.ArgumentParser(
        prog=f"yoke local-postgres {verb}",
        description=f"{verb.capitalize()} the embedded local-universe Postgres.",
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    return parse_or_usage_error(
        parser, args, TOOL_SHAPED_USAGE[f"yoke local-postgres {verb}"],
    )


def _lifecycle_run(operation: Callable[[], Dict[str, Any]], json_mode: bool) -> int:
    try:
        payload = operation()
    except setup.LocalUniverseSetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for key in ("root", "initialized", "running", "binaries", "dsn"):
            if key in payload:
                print(f"{key}={payload[key]}")
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


def _emit_for(json_mode: bool) -> Callable[[str], None]:
    """Progress lines go to stderr in JSON mode so stdout stays parseable."""
    stream = sys.stderr if json_mode else sys.stdout
    return lambda line: print(line, file=stream, flush=True)


def _print_init_summary(report: Dict[str, Any]) -> None:
    born = report.get("born")
    print("yoke init --local: " + ("universe created" if born
                                   else "universe already live"))
    cluster = report.get("cluster") or {}
    if cluster.get("root"):
        print(f"cluster: {cluster['root']} (running={cluster.get('running')})")
    org = report.get("org") or {}
    if org:
        print(f"org: {org.get('name')} (slug={org.get('slug')})")
    connection = report.get("connection") or {}
    if connection.get("written"):
        print("machine config: connections.local written")
    else:
        print("machine config: connections.local already matches")
    print(f"active env: {report.get('active_env')}")


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("init",): init,
    ("local", "demo", "seed"): local_demo_seed,
    ("local-postgres", "start"): local_postgres_start,
    ("local-postgres", "stop"): local_postgres_stop,
    ("local-postgres", "status"): local_postgres_status,
    ("universe", "export"): universe_export,
}


__all__ = [
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "init",
    "local_demo_seed",
    "local_postgres_start",
    "local_postgres_status",
    "local_postgres_stop",
    "universe_export",
]
