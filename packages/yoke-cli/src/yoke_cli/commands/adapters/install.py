"""Project-install adapters for the ``yoke`` CLI.

``yoke project install`` / ``refresh`` / ``uninstall`` write the
project-local operating layer into an external project repo. Yoke
source checkout setup lives under ``yoke dev setup``. Sibling of
:mod:`yoke_cli.commands.adapters.config_write`: these run the domain functions
in-process on this machine (the repo lives here), printing the report
JSON. Env selection rides the CLI's global ``--env`` flag, which exports
``YOKE_ENV`` around dispatch.
"""

from __future__ import annotations

import argparse
import json
from typing import List

from yoke_cli.commands._helpers import (
    attach_field_note_footer,
    parse_or_usage_error,
)
from yoke_cli.config.machine_config import MachineConfigError
from yoke_cli.config.writer import MachineConfigWriteError
from yoke_cli.project_install import runner as project_install_runner
from yoke_cli.project_install.files import ProjectInstallError
from yoke_contracts.machine_config.schema import MachineConfigContractError

PROJECT_INSTALL_USAGE = (
    "yoke project install [REPO_ROOT] [--project-id N] [--config PATH] [--json]"
)
PROJECT_REFRESH_USAGE = (
    "yoke project refresh [REPO_ROOT] [--project-id N] [--config PATH] [--json]"
)
PROJECT_UNINSTALL_USAGE = (
    "yoke project uninstall [REPO_ROOT] [--config PATH] [--json]"
)


def _install_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog)
    parser.add_argument("repo_root", nargs="?", default=None,
                        help="Project repo root (default: cwd).")
    parser.add_argument("--project-id", dest="project_id", type=int,
                        default=None)
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    attach_field_note_footer(parser)
    return parser


def _run_install(args: List[str], usage: str, prog: str,
                 operation: str) -> int:
    parsed = parse_or_usage_error(_install_parser(prog), args, usage)
    if parsed is None:
        return 2
    domain = _project_install_domain()
    fn = domain.install if operation == "install" else domain.refresh
    return _run(lambda: fn(
        parsed.repo_root,
        project_id=parsed.project_id,
        config_path=parsed.config_path,
        mode=None,
    ))


def project_install(args: List[str]) -> int:
    return _run_install(args, PROJECT_INSTALL_USAGE,
                        "yoke project install", "install")


def project_refresh(args: List[str]) -> int:
    return _run_install(args, PROJECT_REFRESH_USAGE,
                        "yoke project refresh", "refresh")


def project_uninstall(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke project uninstall")
    parser.add_argument("repo_root", nargs="?", default=None,
                        help="Project repo root (default: cwd).")
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, PROJECT_UNINSTALL_USAGE)
    if parsed is None:
        return 2
    domain = _project_install_domain()
    return _run(lambda: domain.uninstall(
        parsed.repo_root, config_path=parsed.config_path,
    ))


def _run(operation) -> int:
    import sys

    try:
        result = operation()
    except _install_errors() as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


def _project_install_domain():
    return project_install_runner


def _install_errors():
    return (
        ProjectInstallError,
        MachineConfigError,
        MachineConfigContractError,
        MachineConfigWriteError,
    )


__all__ = [
    "PROJECT_INSTALL_USAGE",
    "PROJECT_REFRESH_USAGE",
    "PROJECT_UNINSTALL_USAGE",
    "project_install",
    "project_refresh",
    "project_uninstall",
]
