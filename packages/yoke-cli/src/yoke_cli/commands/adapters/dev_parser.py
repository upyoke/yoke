"""Argument parsers for ``yoke dev setup`` and ``yoke dev db-admin setup``."""

from __future__ import annotations

import argparse

from yoke_cli.commands._helpers import add_json_arg
from yoke_cli.config import dev_setup as dev_setup_config
from yoke_cli.commands.adapters.dev_setup_flags import (
    _add_authority_args,
    _add_secret_args,
    _add_tunnel_args,
)

_CONFIG_HELP = "Machine config file to write; default: the standard location."
_ACTIVE_HELP = "Make the new connection the active one."
_YES_HELP = "Apply the plan."
_DRY_RUN_HELP = "Print the plan without applying it (the default)."


def build_setup_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke dev setup",
        description=(
            "Plan or apply Yoke source-dev/admin setup. This is the only "
            "command that owns source-link repair, editable install bootstrap, "
            "and local-postgres admin connector entries."
        ),
    )
    parser.add_argument(
        "checkout_or_dsn",
        nargs="?",
        default=None,
        help="Source checkout path, or a DSN; default checkout: current directory.",
    )
    parser.add_argument("dsn_value", nargs="?", default=None, help="Admin DSN.")
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help=_CONFIG_HELP,
    )
    parser.add_argument(
        "--admin-env",
        dest="env_name",
        default=dev_setup_config.DEFAULT_ADMIN_ENV,
        help="Name of the admin connection to write.",
    )
    _add_secret_args(parser)
    parser.add_argument("--set-active-env", action="store_true", help=_ACTIVE_HELP)
    parser.add_argument(
        "--editable-install",
        action="store_true",
        help="Install the checkout's packages in editable mode.",
    )
    parser.add_argument(
        "--with-test-postgres",
        action="store_true",
        help="Use the local test Postgres instead of a DSN you supply.",
    )
    parser.add_argument("--postgres-host", default=None, help="Postgres host name.")
    parser.add_argument(
        "--postgres-port",
        type=int,
        default=None,
        help="Postgres port number.",
    )
    _add_tunnel_args(parser)
    _add_authority_args(parser)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--yes", dest="apply", action="store_true", help=_YES_HELP)
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help=_DRY_RUN_HELP,
    )
    parser.set_defaults(apply=False, dry_run=False)
    add_json_arg(parser)
    return parser


def build_db_admin_setup_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke dev db-admin setup",
        description=(
            "Plan or apply a machine-local db-admin Postgres profile from "
            "DB-backed deploy-environment infrastructure. By default it "
            "reaches the Yoke control-plane database, whose identity is read "
            "through a named tenant-routed HTTPS control plane; --database "
            "MODEL reaches the project's own database declared under that "
            "model of its migration_model capability instead. Endpoint and "
            "managed-secret authority come from Pulumi without materializing "
            "the secret value."
        ),
    )
    parser.add_argument("env_name", help="Deploy environment to reach, such as prod.")
    parser.add_argument(
        "--project", default=None, help="Project that owns the environment."
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help=_CONFIG_HELP,
    )
    parser.add_argument(
        "--database",
        default=None,
        metavar="MODEL",
        help=(
            "Reach the project's own database declared as migration_model "
            "models.MODEL.authoritative_db (profile <project>-<env>-MODEL-db-admin)."
        ),
    )
    parser.add_argument(
        "--admin-env",
        default=None,
        help="Name of the profile to write; default: derived from ENV.",
    )
    parser.add_argument(
        "--local-port",
        type=int,
        default=None,
        help="Local port for the SSH forward; default: one per environment.",
    )
    parser.add_argument(
        "--secret-name",
        default=None,
        help="Managed secret holding the DSN; default: derived from project and ENV.",
    )
    parser.add_argument(
        "--control-plane-env",
        default=None,
        help=(
            "Named HTTPS connection used for tenant-routed current_database() "
            "identity or the --database declaration read (defaults to ENV "
            "only when that connection is HTTPS)."
        ),
    )
    parser.add_argument("--set-active-env", action="store_true", help=_ACTIVE_HELP)
    parser.add_argument(
        "--allow-render-only",
        action="store_true",
        help="Allow an environment that is still render-only.",
    )
    production = parser.add_mutually_exclusive_group()
    production.add_argument(
        "--prod",
        dest="prod",
        action="store_true",
        help="Mark the profile as a production connection.",
    )
    production.add_argument(
        "--non-prod",
        dest="prod",
        action="store_false",
        help="Mark the profile as non-production (the default).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--yes", dest="apply", action="store_true", help=_YES_HELP)
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help=_DRY_RUN_HELP,
    )
    parser.set_defaults(apply=False, dry_run=False, prod=False)
    add_json_arg(parser)
    return parser


__all__ = ["build_db_admin_setup_parser", "build_setup_parser"]
