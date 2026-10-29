"""``yoke dev`` local source-checkout/admin commands."""

from __future__ import annotations

import argparse
import sys
from typing import List

from yoke_cli.commands._helpers import (
    parse_or_usage_error,
)
from yoke_cli.config import db_admin_dsn_exec
from yoke_cli.config import db_admin_setup as db_admin_setup_config
from yoke_cli.config import dev_setup as dev_setup_config
from yoke_cli.config.writer import MachineConfigWriteError
from yoke_cli.project_install.files import ProjectInstallError

from yoke_cli.commands.adapters.dev_parser import (
    build_db_admin_setup_parser,
    build_setup_parser,
)
from yoke_cli.commands.adapters.dev_setup_flags import (
    DevSetupAdapterError,
    _checkout_and_positional_dsn,
    _postgres,
    _authority,
)

DEV_SETUP_USAGE = (
    "yoke dev setup [CHECKOUT] [DSN] [--config PATH] [--admin-env ENV] "
    "[--dsn DSN | --dsn-file PATH | --dsn-stdin] [--set-active-env] "
    "[--editable-install] [--with-test-postgres] "
    "[--postgres-host HOST] [--postgres-port PORT] "
    "[--tunnel-bastion USER@HOST --tunnel-identity-file PATH "
    "--tunnel-remote-host HOST --tunnel-remote-port PORT] "
    "[--authority-kind KIND --authority-infra-dir DIR --authority-stack STACK "
    "--authority-region REGION --authority-database-name NAME] "
    "[--yes | --dry-run] [--json]"
)
DEV_DB_ADMIN_SETUP_USAGE = (
    "yoke dev db-admin setup ENV [--project P] [--config PATH] [--database MODEL] "
    "[--admin-env NAME] [--control-plane-env CONNECTION] "
    "[--local-port PORT] [--secret-name NAME] [--set-active-env] "
    "[--allow-render-only] [--prod | --non-prod] "
    "[--yes | --dry-run] [--json]"
)
DEV_DB_ADMIN_EXEC_USAGE = (
    "yoke dev db-admin exec ADMIN_ENV --dsn-var NAME -- <command> [args...]"
)


def dev_setup(args: List[str]) -> int:
    parser = build_setup_parser()
    parser.usage = DEV_SETUP_USAGE
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


def dev_db_admin_setup(args: List[str]) -> int:
    parser = build_db_admin_setup_parser()
    parser.usage = DEV_DB_ADMIN_SETUP_USAGE
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
            database=parsed.database,
        )
    except db_admin_setup_config.DbAdminSetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(db_admin_setup_config.dumps_json(report), end="")
    else:
        print(db_admin_setup_config.render_human(report), end="")
    return 0


def dev_db_admin_exec(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke dev db-admin exec",
        usage=DEV_DB_ADMIN_EXEC_USAGE,
        description=(
            "Run one command with a db-admin profile's DSN in a variable you "
            "name, set for that subprocess only. The managed secret is read "
            "from AWS through the project's aws-admin capability at run time "
            "and the profile's SSH forward is brought up first; the DSN is "
            "never printed, logged, or written to disk."
        ),
    )
    parser.add_argument("admin_env", metavar="ADMIN_ENV", help="Profile to use.")
    parser.add_argument(
        "--dsn-var",
        required=True,
        metavar="NAME",
        help="Environment variable that receives the DSN.",
    )
    split = args.index("--") if "--" in args else len(args)
    parsed = parse_or_usage_error(parser, args[:split], DEV_DB_ADMIN_EXEC_USAGE)
    if parsed is None:
        return 2
    command = list(args[split + 1 :])
    try:
        return db_admin_dsn_exec.run(parsed.admin_env, parsed.dsn_var, command)
    except db_admin_dsn_exec.DbAdminExecRefusal as exc:
        for line in exc.report_lines():
            print(line, file=sys.stderr)
        return exc.exit_code


__all__ = [
    "DEV_DB_ADMIN_EXEC_USAGE",
    "DEV_DB_ADMIN_SETUP_USAGE",
    "DEV_SETUP_USAGE",
    "dev_db_admin_exec",
    "dev_db_admin_setup",
    "dev_setup",
]
