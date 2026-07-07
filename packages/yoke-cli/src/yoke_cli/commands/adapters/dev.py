"""``yoke dev`` local source-checkout/admin commands."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    attach_field_note_footer,
    parse_or_usage_error,
)
from yoke_cli.config import db_admin_setup as db_admin_setup_config
from yoke_cli.config import dev_setup as dev_setup_config
from yoke_cli.config.writer import MachineConfigWriteError
from yoke_cli.project_install.files import ProjectInstallError

DEV_SETUP_USAGE = (
    "yoke dev setup [CHECKOUT] [DSN] [--config PATH] [--env ENV] "
    "[--dsn DSN | --dsn-file PATH | --dsn-stdin] [--set-active-env] "
    "[--editable-install] [--with-test-postgres] "
    "[--postgres-host HOST] [--postgres-port PORT] "
    "[--tunnel-bastion USER@HOST --tunnel-identity-file PATH "
    "--tunnel-remote-host HOST --tunnel-remote-port PORT] "
    "[--authority-kind KIND --authority-infra-dir DIR --authority-stack STACK "
    "--authority-region REGION --authority-database-name NAME] "
    "[--yes | --dry-run] [--json]"
)
DEV_PATH_SNAPSHOT_PREWARM_USAGE = (
    "yoke dev path-snapshot-prewarm [PROJECT_ID] [--json]"
)
DEV_DB_ADMIN_SETUP_USAGE = (
    "yoke dev db-admin setup ENV [--project PROJECT] [--admin-env ENV] "
    "[--local-port PORT] [--secret-name NAME] [--set-active-env] "
    "[--allow-render-only] [--yes | --dry-run] [--json]"
)
PROJECT_ID_ENV = "YOKE_PROJECT_ID"
DEFAULT_PROJECT_ID = "yoke"


def dev_setup(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke dev setup",
        description=(
            "Plan or apply Yoke source-dev/admin setup. This is the only "
            "command that owns source-link repair, editable install bootstrap, "
            "and local-postgres admin connector entries."
        ),
    )
    parser.add_argument("checkout_or_dsn", nargs="?", default=None)
    parser.add_argument("dsn_value", nargs="?", default=None)
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--env", dest="env_name",
                        default=dev_setup_config.DEFAULT_ADMIN_ENV)
    _add_secret_args(parser)
    parser.add_argument("--set-active-env", action="store_true")
    parser.add_argument("--editable-install", action="store_true")
    parser.add_argument("--with-test-postgres", action="store_true")
    parser.add_argument("--postgres-host", default=None)
    parser.add_argument("--postgres-port", type=int, default=None)
    _add_tunnel_args(parser)
    _add_authority_args(parser)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--yes", dest="apply", action="store_true")
    mode.add_argument("--dry-run", dest="dry_run", action="store_true")
    parser.set_defaults(apply=False, dry_run=False)
    add_json_arg(parser)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, DEV_SETUP_USAGE)
    if parsed is None:
        return 2

    try:
        checkout, positional_dsn = _checkout_and_positional_dsn(parsed)
        if positional_dsn and any((
            parsed.dsn, parsed.dsn_file, parsed.dsn_stdin,
        )):
            raise DevSetupAdapterError(
                "positional DSN is mutually exclusive with --dsn, "
                "--dsn-file, and --dsn-stdin"
            )
        report = dev_setup_config.build_report(
            checkout=checkout,
            config_path=parsed.config_path,
            env_name=parsed.env_name,
            dsn=parsed.dsn or positional_dsn,
            dsn_file=parsed.dsn_file,
            dsn_stdin_value=sys.stdin.read().strip() if parsed.dsn_stdin else None,
            apply=parsed.apply,
            set_active_env=parsed.set_active_env,
            editable_install=parsed.editable_install,
            with_test_postgres=parsed.with_test_postgres,
            postgres=_postgres(parsed),
            authority=_authority(parsed),
        )
    except (DevSetupAdapterError, ProjectInstallError, MachineConfigWriteError,
            dev_setup_config.DevSetupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(dev_setup_config.dumps_json(report), end="")
    else:
        print(dev_setup_config.render_human(report), end="")
    return 0


def dev_path_snapshot_prewarm(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke dev path-snapshot-prewarm",
        description=(
            "Source-dev/admin path-snapshot prewarm. Builds the HEAD "
            "snapshot and integration-target snapshot through the local "
            "Yoke DB authority; product git hooks never invoke this "
            "silently."
        ),
    )
    parser.add_argument(
        "project_id",
        nargs="?",
        default=None,
        help="Project id from the projects table (default: $YOKE_PROJECT_ID or yoke).",
    )
    add_json_arg(parser)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(
        parser, args, DEV_PATH_SNAPSHOT_PREWARM_USAGE,
    )
    if parsed is None:
        return 2

    project_id = parsed.project_id or os.environ.get(PROJECT_ID_ENV) or DEFAULT_PROJECT_ID
    try:
        head_snapshot_id, integration_snapshot_id = _run_path_snapshot_prewarm(
            project_id,
        )
    except Exception as exc:
        print(
            "error: source-dev/admin path-snapshot prewarm failed: "
            f"{exc}",
            file=sys.stderr,
        )
        return 1
    payload = {
        "operation": "dev.path_snapshot_prewarm",
        "project_id": project_id,
        "head_snapshot_id": head_snapshot_id,
        "integration_snapshot_id": integration_snapshot_id,
    }
    if parsed.json_mode:
        print(json.dumps(payload, indent=2))
    else:
        print(
            "path-snapshot prewarm complete: "
            f"project={project_id} head={head_snapshot_id} "
            f"integration={integration_snapshot_id}"
        )
    return 0


def dev_db_admin_setup(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke dev db-admin setup",
        description=(
            "Plan or apply a machine-local <env>-db-admin Postgres profile "
            "from DB-backed deploy-environment authority. The DSN is "
            "resolved from Pulumi outputs and the RDS secret, localized to "
            "the configured SSH tunnel, and stored as a machine secret."
        ),
    )
    parser.add_argument("env_name")
    parser.add_argument("--project", default=db_admin_setup_config.DEFAULT_PROJECT)
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--admin-env", default=None)
    parser.add_argument("--local-port", type=int, default=None)
    parser.add_argument("--secret-name", default=None)
    parser.add_argument("--set-active-env", action="store_true")
    parser.add_argument("--allow-render-only", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--yes", dest="apply", action="store_true")
    mode.add_argument("--dry-run", dest="dry_run", action="store_true")
    parser.set_defaults(apply=False, dry_run=False)
    add_json_arg(parser)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, DEV_DB_ADMIN_SETUP_USAGE)
    if parsed is None:
        return 2
    try:
        report = db_admin_setup_config.build_report(
            project=parsed.project,
            env_name=parsed.env_name,
            config_path=parsed.config_path,
            admin_env=parsed.admin_env,
            local_port=parsed.local_port,
            secret_label=parsed.secret_name,
            apply=parsed.apply,
            set_active_env=parsed.set_active_env,
            allow_render_only=parsed.allow_render_only,
        )
    except db_admin_setup_config.DbAdminSetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(db_admin_setup_config.dumps_json(report), end="")
    else:
        print(db_admin_setup_config.render_human(report), end="")
    return 0


def _run_path_snapshot_prewarm(project_id: str) -> tuple[int, int | None]:
    db_helpers = importlib.import_module("yoke_core.domain.db_helpers")
    path_snapshots = importlib.import_module("yoke_core.domain.path_snapshots")
    warm = importlib.import_module(
        "yoke_core.domain.path_snapshots_integration_warm"
    )
    conn = db_helpers.connect()
    try:
        head_snapshot_id = path_snapshots.build_head_snapshot(conn, project_id)
        integration_snapshot_id = warm.ensure_integration_target_snapshot(
            conn, project_id,
        )
    finally:
        conn.close()
    return int(head_snapshot_id), (
        None if integration_snapshot_id is None else int(integration_snapshot_id)
    )


class DevSetupAdapterError(RuntimeError):
    """Adapter argument combinations are incomplete."""


def _checkout_and_positional_dsn(
    parsed: argparse.Namespace,
) -> tuple[str | None, str | None]:
    first = parsed.checkout_or_dsn
    second = parsed.dsn_value
    if second is not None:
        return first, second
    if first is not None and _looks_like_postgres_dsn(first):
        return None, first
    return first, None


def _looks_like_postgres_dsn(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered.startswith(("postgres://", "postgresql://"))
        or any(token in lowered for token in ("host=", "dbname=", "sslmode="))
    )


def _add_secret_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dsn", dest="dsn", default=None)
    parser.add_argument("--dsn-file", dest="dsn_file", default=None)
    parser.add_argument("--dsn-stdin", dest="dsn_stdin", action="store_true")


def _add_tunnel_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tunnel-bastion", default=None)
    parser.add_argument("--tunnel-identity-file", default=None)
    parser.add_argument("--tunnel-remote-host", default=None)
    parser.add_argument("--tunnel-remote-port", type=int, default=None)


def _add_authority_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--authority-kind", default=None)
    parser.add_argument("--authority-infra-dir", default=None)
    parser.add_argument("--authority-stack", default=None)
    parser.add_argument("--authority-region", default=None)
    parser.add_argument("--authority-database-name", default=None)


def _postgres(parsed: argparse.Namespace) -> dict[str, Any]:
    postgres = {
        key: value for key, value in (
            ("host", parsed.postgres_host),
            ("port", parsed.postgres_port),
        ) if value is not None
    }
    tunnel = _tunnel(parsed)
    if tunnel:
        postgres["tunnel"] = tunnel
    return postgres


def _tunnel(parsed: argparse.Namespace) -> dict[str, Any]:
    values = {
        "bastion": parsed.tunnel_bastion,
        "identity_file": parsed.tunnel_identity_file,
        "remote_host": parsed.tunnel_remote_host,
        "remote_port": parsed.tunnel_remote_port,
    }
    if not any(value is not None for value in values.values()):
        return {}
    missing = [key for key, value in values.items() if value is None]
    if missing:
        raise DevSetupAdapterError(
            "--tunnel-* options must be supplied together; missing "
            + ", ".join(missing)
        )
    values["kind"] = "ssh"
    return values


def _authority(parsed: argparse.Namespace) -> dict[str, Any]:
    values = {
        "kind": parsed.authority_kind,
        "infra_dir": parsed.authority_infra_dir,
        "stack": parsed.authority_stack,
        "region": parsed.authority_region,
        "database_name": parsed.authority_database_name,
    }
    if not any(value for value in values.values()):
        return {}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise DevSetupAdapterError(
            "--authority-* options must be supplied together; missing "
            + ", ".join(missing)
        )
    return {
        "kind": values["kind"],
        "infra_dir": values["infra_dir"],
        "location": {
            "stack": values["stack"],
            "region": values["region"],
            "database_name": values["database_name"],
        },
    }


__all__ = [
    "DEFAULT_PROJECT_ID",
    "DEV_DB_ADMIN_SETUP_USAGE",
    "DEV_PATH_SNAPSHOT_PREWARM_USAGE",
    "DEV_SETUP_USAGE",
    "PROJECT_ID_ENV",
    "dev_db_admin_setup",
    "dev_path_snapshot_prewarm",
    "dev_setup",
]
