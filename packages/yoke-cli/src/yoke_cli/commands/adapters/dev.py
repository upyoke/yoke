"""``yoke dev`` local source-checkout/admin commands."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    attach_help_trailer,
    parse_or_usage_error,
)
from yoke_cli.config import db_admin_setup as db_admin_setup_config
from yoke_cli.config import dev_setup as dev_setup_config
from yoke_cli.config.writer import MachineConfigWriteError
from yoke_cli.project_install.files import ProjectInstallError

from yoke_cli.config.project_selection import required_project_context
from yoke_cli.commands.adapters.dev_setup_flags import (
    DevSetupAdapterError,
    _checkout_and_positional_dsn,
    _add_secret_args,
    _add_tunnel_args,
    _add_authority_args,
    _postgres,
    _authority,
)

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
DEV_PATH_SNAPSHOT_PREWARM_USAGE = "yoke dev path-snapshot-prewarm [PROJECT_ID] [--json]"
DEV_DB_ADMIN_SETUP_USAGE = (
    "yoke dev db-admin setup ENV [--project PROJECT] [--admin-env ENV] "
    "[--control-plane-env CONNECTION_ENV] "
    "[--local-port PORT] [--secret-name NAME] [--set-active-env] "
    "[--allow-render-only] [--prod | --non-prod] "
    "[--yes | --dry-run] [--json]"
)
PROJECT_ID_ENV = "YOKE_PROJECT_ID"


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
    parser.add_argument(
        "--env", dest="env_name", default=dev_setup_config.DEFAULT_ADMIN_ENV
    )
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
    attach_help_trailer(parser)
    parsed = parse_or_usage_error(parser, args, DEV_SETUP_USAGE)
    if parsed is None:
        return 2

    try:
        checkout, positional_dsn = _checkout_and_positional_dsn(parsed)
        if positional_dsn and any(
            (
                parsed.dsn,
                parsed.dsn_file,
                parsed.dsn_stdin,
            )
        ):
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
    except (
        DevSetupAdapterError,
        ProjectInstallError,
        MachineConfigWriteError,
        dev_setup_config.DevSetupError,
    ) as exc:
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
        help="Project id (explicit value, YOKE_PROJECT, or the checkout binding).",
    )
    add_json_arg(parser)
    attach_help_trailer(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        DEV_PATH_SNAPSHOT_PREWARM_USAGE,
    )
    if parsed is None:
        return 2

    try:
        project_id = required_project_context(parsed.project_id)
        head_snapshot_id, integration_snapshot_id = _run_path_snapshot_prewarm(
            project_id,
        )
    except Exception as exc:
        print(
            f"error: source-dev/admin path-snapshot prewarm failed: {exc}",
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
            "from DB-backed deploy-environment infrastructure. The database "
            "identity is read through a named tenant-routed HTTPS control "
            "plane; endpoint and managed-secret authority come from Pulumi "
            "without materializing the secret value."
        ),
    )
    parser.add_argument("env_name")
    parser.add_argument("--project", default=None)
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--admin-env", default=None)
    parser.add_argument("--local-port", type=int, default=None)
    parser.add_argument("--secret-name", default=None)
    parser.add_argument(
        "--control-plane-env",
        default=None,
        help=(
            "Named HTTPS connection used for tenant-routed current_database() "
            "identity (defaults to ENV only when that connection is HTTPS)."
        ),
    )
    parser.add_argument("--set-active-env", action="store_true")
    parser.add_argument("--allow-render-only", action="store_true")
    production = parser.add_mutually_exclusive_group()
    production.add_argument("--prod", dest="prod", action="store_true")
    production.add_argument("--non-prod", dest="prod", action="store_false")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--yes", dest="apply", action="store_true")
    mode.add_argument("--dry-run", dest="dry_run", action="store_true")
    parser.set_defaults(apply=False, dry_run=False, prod=False)
    add_json_arg(parser)
    attach_help_trailer(parser)
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
            control_plane_env=parsed.control_plane_env,
            apply=parsed.apply,
            set_active_env=parsed.set_active_env,
            allow_render_only=parsed.allow_render_only,
            prod=parsed.prod,
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
    warm = importlib.import_module("yoke_core.domain.path_snapshots_integration_warm")
    conn = db_helpers.connect()
    try:
        head_snapshot_id = path_snapshots.build_head_snapshot(conn, project_id)
        integration_snapshot_id = warm.ensure_integration_target_snapshot(
            conn,
            project_id,
        )
    finally:
        conn.close()
    return int(head_snapshot_id), (
        None if integration_snapshot_id is None else int(integration_snapshot_id)
    )


__all__ = [
    "DEV_DB_ADMIN_SETUP_USAGE",
    "DEV_PATH_SNAPSHOT_PREWARM_USAGE",
    "DEV_SETUP_USAGE",
    "PROJECT_ID_ENV",
    "dev_db_admin_setup",
    "dev_path_snapshot_prewarm",
    "dev_setup",
]
