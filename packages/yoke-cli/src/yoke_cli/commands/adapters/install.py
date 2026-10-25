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
import json

import argparse
from yoke_cli.transport.human_values import write_local
from typing import List

from yoke_cli.commands._helpers import (
    parse_or_usage_error,
)
from yoke_cli.config.machine_config import MachineConfigError
from yoke_cli.config.writer import MachineConfigWriteError
from yoke_cli.project_install import publication_outcome
from yoke_cli.project_install import runner as project_install_runner
from yoke_cli.project_install.files import ProjectInstallError
from yoke_contracts.machine_config.schema import MachineConfigContractError

PROJECT_INSTALL_USAGE = (
    "yoke project install [REPO_ROOT] [--project-id N] [--config PATH] "
    "[--force] [--no-commit] [--no-publish] [--json]"
)
PROJECT_REFRESH_USAGE = (
    "yoke project refresh [REPO_ROOT] [--project-id N] [--config PATH] "
    "[--force] [--no-commit] [--no-publish] "
    "[--source-checkout PATH] [--project-slug SLUG] "
    "[--manifest-from PATH] [--apply] [--json]"
)

# Exit 0 means the layer is installed AND on its remote. A run that wrote and
# committed the layer but could not publish it is neither a success nor an
# install failure, so it gets its own status rather than borrowing either.
PUBLICATION_PENDING_EXIT = 3
PROJECT_UNINSTALL_USAGE = "yoke project uninstall [REPO_ROOT] [--config PATH] [--json]"


def _install_parser(prog: str, usage: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter, prog=prog, usage=usage
    )
    _add_root_and_config(parser)
    parser.add_argument(
        "--project-id",
        dest="project_id",
        type=int,
        default=None,
        metavar="N",
        help="Project id; default: the checkout's mapped project.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Proceed despite a dirty working tree or a checkout that is not "
            "on the project default branch."
        ),
    )
    parser.add_argument(
        "--no-commit",
        dest="no_commit",
        action="store_true",
        help="Write the bundle without committing the touched paths.",
    )
    parser.add_argument(
        "--no-publish",
        dest="no_publish",
        action="store_true",
        help=(
            "Commit the touched paths without pushing them to the branch's "
            "remote. A run that tries and cannot exits "
            f"{PUBLICATION_PENDING_EXIT} and names the recovery."
        ),
    )
    parser.add_argument(
        "--json", dest="json_mode", action="store_true", help="Print JSON output."
    )
    return parser


def _add_root_and_config(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=None,
        metavar="REPO_ROOT",
        help="Project repo root (default: the current directory).",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        metavar="PATH",
        help="Machine config file to use.",
    )


def _refresh_parser() -> argparse.ArgumentParser:
    parser = _install_parser("yoke project refresh", PROJECT_REFRESH_USAGE)
    source_group = parser.add_argument_group(
        "refresh from a local Yoke source checkout (source developers)"
    )
    source_group.add_argument(
        "--source-checkout",
        metavar="PATH",
        help=(
            "Yoke source checkout to build an unreleased local bundle from. "
            "Only previews unless --apply is also passed."
        ),
    )
    source_group.add_argument(
        "--project-slug",
        metavar="SLUG",
        help=(
            "The project's slug. Required when an older install manifest does "
            "not record project_slug."
        ),
    )
    source_group.add_argument(
        "--manifest-from",
        metavar="PATH",
        help=(
            "An existing install-manifest.json to start from when the target "
            "is a linked worktree that lacks its own (gitignored) manifest."
        ),
    )
    source_group.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Write the local-source preview. This never writes machine "
            "registration or server snapshot state."
        ),
    )
    return parser


def _run_install(args: List[str], usage: str, prog: str, operation: str) -> int:
    parsed = parse_or_usage_error(_install_parser(prog, usage), args, usage)
    if parsed is None:
        return 2
    domain = _project_install_domain()
    fn = domain.install if operation == "install" else domain.refresh
    return _run(
        lambda: fn(
            parsed.repo_root,
            project_id=parsed.project_id,
            config_path=parsed.config_path,
            mode=None,
            force=parsed.force,
            commit=not parsed.no_commit,
            publish_skip_reason=_publish_skip_reason(parsed),
        ),
        json_mode=parsed.json_mode,
        config_path=parsed.config_path,
    )


def _publish_skip_reason(parsed: argparse.Namespace) -> str:
    return publication_outcome.DISABLED_REASON if parsed.no_publish else ""


def project_install(args: List[str]) -> int:
    return _run_install(args, PROJECT_INSTALL_USAGE, "yoke project install", "install")


def project_refresh(args: List[str]) -> int:
    parsed = parse_or_usage_error(_refresh_parser(), args, PROJECT_REFRESH_USAGE)
    if parsed is None:
        return 2
    if parsed.apply and not parsed.source_checkout:
        import sys

        print(
            "error: --apply is valid only with --source-checkout",
            file=sys.stderr,
        )
        return 2
    if parsed.manifest_from and not parsed.source_checkout:
        import sys

        print(
            "error: --manifest-from is valid only with --source-checkout",
            file=sys.stderr,
        )
        return 2
    if parsed.source_checkout:
        from yoke_cli.project_install.local_source import refresh_from_source

        return _run(
            lambda: refresh_from_source(
                parsed.repo_root,
                source_checkout=parsed.source_checkout,
                project_id=parsed.project_id,
                project_slug=parsed.project_slug,
                manifest_from=parsed.manifest_from,
                apply=parsed.apply,
                force=parsed.force,
                commit=not parsed.no_commit,
            ),
            json_mode=parsed.json_mode,
            config_path=parsed.config_path,
        )
    return _run(
        lambda: _project_install_domain().refresh(
            parsed.repo_root,
            project_id=parsed.project_id,
            config_path=parsed.config_path,
            mode=None,
            force=parsed.force,
            commit=not parsed.no_commit,
            publish_skip_reason=_publish_skip_reason(parsed),
        ),
        json_mode=parsed.json_mode,
        config_path=parsed.config_path,
    )


def project_uninstall(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke project uninstall",
        usage=PROJECT_UNINSTALL_USAGE,
        description="Remove this checkout's installed layer, installer-owned registration and the exact folder trust Yoke recorded writing. Trust Yoke did not write is left alone; trust edited after Yoke wrote it stays and is reported. Shared or unproven registration stays with a reason and recovery, and the manifest stays for retry. Credentials, shared tools and server history stay intact.",
    )
    _add_root_and_config(parser)
    parser.add_argument(
        "--json", dest="json_mode", action="store_true", help="Print JSON output."
    )
    parsed = parse_or_usage_error(parser, args, PROJECT_UNINSTALL_USAGE)
    if parsed is None:
        return 2
    domain = _project_install_domain()
    return _run(
        lambda: domain.uninstall(
            parsed.repo_root,
            config_path=parsed.config_path,
        ),
        json_mode=parsed.json_mode,
        config_path=parsed.config_path,
    )


def _run(operation, *, json_mode: bool = False, config_path=None) -> int:
    import sys

    try:
        result = operation()
    except _install_errors() as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    setup = None
    if (
        not result.get("preview")
        and result.get("project_id")
        and result.get("operation") in ("install", "refresh")
    ):
        from yoke_cli.config.setup_facts_summary import read_project

        setup = read_project(
            result["repo_root"], project=result["project_id"], config_path=config_path
        )
        result["next_action"] = setup["next_action"]
    if json_mode:
        if setup is not None:
            result["setup_summary"] = setup["lines"]
        print(json.dumps(result, indent=2))
    else:
        write_local(result, sys.stdout)
        if setup:
            print("\n".join(setup["lines"]))
    if publication_outcome.is_publication_pending(result):
        return PUBLICATION_PENDING_EXIT
    if result.get("outcome") == "partial":
        return 1
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
    "PUBLICATION_PENDING_EXIT",
    "PROJECT_REFRESH_USAGE",
    "PROJECT_UNINSTALL_USAGE",
    "project_install",
    "project_refresh",
    "project_uninstall",
]
