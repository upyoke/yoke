"""Tool-shaped ``yoke init`` / ``yoke local-postgres`` / ``yoke universe``
commands.

Tool-shaped product operations with NO dispatcher function id: local setup and
import manage the machine's own universe, while export either uses that direct
database authority or streams from an authenticated self-host server. Like the
other tool-shaped families they resolve via the tool-shaped table after
SUBCOMMAND_REGISTRY misses.

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
import json
import sys
from typing import Any, Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands.local_demo_seed_command import DEMO_SEED_USAGE, local_demo_seed
from yoke_cli.commands.local_universe_import_command import universe_import
from yoke_cli.commands.local_universe_usage import IMPORT_USAGE
from yoke_cli.config import local_universe_setup as setup
from yoke_cli.config import onboard_destinations
from yoke_cli.config.universe_export_download import (
    UniverseExportDownloadError,
    download_universe,
)
from yoke_cli.transport.https import TransportError, resolve_https_connection

AdapterFn = Callable[[List[str]], int]

INIT_USAGE = (
    "yoke init --local [--admin-name NAME] [--org-name NAME] [--force] "
    "[--config PATH] [--json]"
)

EXPORT_USAGE = "yoke universe export [--out PATH] [--json]"

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke init": INIT_USAGE,
    "yoke local demo seed": DEMO_SEED_USAGE,
    "yoke local-postgres start": "yoke local-postgres start [--json]",
    "yoke local-postgres stop": "yoke local-postgres stop [--json]",
    "yoke local-postgres status": "yoke local-postgres status [--json]",
    "yoke universe export": EXPORT_USAGE,
    "yoke universe import": IMPORT_USAGE,
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
        "--local",
        action="store_true",
        help="Explicit mode selector: the machine-local embedded universe.",
    )
    parser.add_argument(
        "--org-name",
        dest="org_name",
        default=None,
        help="Name for the org identity card (default keeps the existing one).",
    )
    parser.add_argument(
        "--admin-name",
        dest="admin_name",
        default=None,
        help="Your name; required to create a universe: its first admin is you.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace a conflicting existing 'local' machine-config connection.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Machine config path override.",
    )
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
            admin_name=parsed.admin_name,
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
            "between deployment modes. A non-prod local connection uses its "
            "machine-held DSN; a self-host HTTPS connection streams from the "
            "authenticated server export endpoint. Hosted org admins use "
            "Platform's coordinated dashboard download. "
            "Prod-flagged Postgres connections stay operator-only."
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
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
        connection = resolve_https_connection()
        if connection is not None and not onboard_destinations.is_hosted_url(
            connection.api_url
        ):
            report = download_universe(connection, out=parsed.out)
        else:
            report = setup.universe_export(out=parsed.out, emit=emit)
    except (
        setup.LocalUniverseSetupError,
        TransportError,
        UniverseExportDownloadError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"universe export: {report.get('artifact')}")
        print(f"org: {report.get('org')}")
        print(f"format: {report.get('format')} bytes: {report.get('bytes')}")
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
        parser,
        args,
        TOOL_SHAPED_USAGE[f"yoke local-postgres {verb}"],
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


def _emit_for(json_mode: bool) -> Callable[[str], None]:
    """Progress lines go to stderr in JSON mode so stdout stays parseable."""
    stream = sys.stderr if json_mode else sys.stdout
    return lambda line: print(line, file=stream, flush=True)


def _print_init_summary(report: Dict[str, Any]) -> None:
    born = report.get("born")
    print(
        "yoke init --local: "
        + ("universe created" if born else "universe already live")
    )
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
    ("universe", "import"): universe_import,
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
