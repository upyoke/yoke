"""Project bootstrap preflight, setup, and verification.

Python owner for project bootstrap. This parent module owns CLI/context
resolution and exposes the focused preflight, setup, and verification
surfaces used by callers.
"""

from __future__ import annotations

import argparse
import os
import shutil  # noqa: F401  # re-export so tests can patch ``bootstrap_project.shutil.which``
import sys
from pathlib import Path
from typing import Optional

from yoke_core.domain.worktree import resolve_main_root

from .bootstrap_project_helpers import (  # noqa: F401
    BootstrapContext,
    SetupConfig,
    _capability_secret,
    _capability_settings,
    _column_exists,
    _connect,
    _decode_base64,
    _expected_workflow_names,
    _load_json,
    _load_setup_config,
    _print_fail,
    _print_pass,
    _query_scalar,
    _run,
    _table_exists,
    _warn,
)
from .bootstrap_project_preflight import run_preflight  # noqa: F401
from .bootstrap_project_setup import run_setup  # noqa: F401
from .bootstrap_project_verify import run_verify  # noqa: F401


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bootstrap-project",
        description="Python owner for bootstrap-project preflight and verification",
    )
    sub = parser.add_subparsers(dest="subcmd", required=True)

    cli = sub.add_parser("cli")
    cli.add_argument("project")
    cli.add_argument("--preflight-only", action="store_true")
    cli.add_argument("--project-root")
    cli.add_argument("--script-dir")
    cli.add_argument("--yoke-db")
    cli.add_argument(
        "--pack",
        action="append",
        default=[],
        help="install this missing Pack; repeat for more than one",
    )

    for name in ("preflight", "setup", "verify"):
        subp = sub.add_parser(name)
        subp.add_argument("project")
        subp.add_argument("--project-root")
        subp.add_argument("--script-dir")
        subp.add_argument("--yoke-db")
        if name == "setup":
            subp.add_argument(
                "--pack",
                action="append",
                default=[],
                help="install this missing Pack; repeat for more than one",
            )
        if name == "verify":
            subp.add_argument("--github-repo")
            subp.add_argument("--ssh-user")
            subp.add_argument("--ssh-host")
            subp.add_argument("--ssh-key-path")
            subp.add_argument("--display-name")

    return parser


def _resolve_context(args: argparse.Namespace) -> BootstrapContext:
    """Build a ``BootstrapContext`` from CLI args with auto-detection fallbacks.

    The CLI may omit ``--project-root``/``--script-dir``/``--yoke-db`` flags;
    explicit values used by unit tests and diagnostics still take precedence.
    """
    if args.project_root:
        project_root = Path(args.project_root)
    else:
        project_root = Path(resolve_main_root())

    if args.yoke_db:
        yoke_db = Path(args.yoke_db)
    else:
        # Postgres is the active Yoke authority. ``ctx.yoke_db`` remains a
        # compatibility token for older helper signatures whose connection
        # factories ignore path values under Postgres.
        yoke_db = project_root / "data" / "yoke.db"

    if args.script_dir:
        script_dir = Path(args.script_dir)
    else:
        script_dir = Path(
            os.environ.get("YOKE_SCRIPTS_DIR")
            or str(project_root / ".agents" / "skills" / "yoke" / "scripts")
        )

    return BootstrapContext(
        project=args.project,
        project_root=project_root,
        script_dir=script_dir,
        yoke_db=yoke_db,
        packs=tuple(dict.fromkeys(getattr(args, "pack", []) or [])),
    )


def main(argv: Optional[list[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    ctx = _resolve_context(args)
    if args.subcmd == "cli":
        preflight_rc = run_preflight(ctx)
        if preflight_rc != 0:
            sys.exit(1)
        if args.preflight_only:
            print("\nPreflight-only mode: skipping setup.")
            sys.exit(0)
        setup_rc = run_setup(ctx)
        if setup_rc != 0:
            sys.exit(2)
        verify_rc = run_verify(ctx)
        sys.exit(0 if verify_rc == 0 else 2)
    if args.subcmd == "preflight":
        sys.exit(run_preflight(ctx))
    if args.subcmd == "setup":
        sys.exit(run_setup(ctx))
    if args.subcmd == "verify":
        sys.exit(
            run_verify(
                ctx,
                github_repo=args.github_repo,
                ssh_user=args.ssh_user,
                ssh_host=args.ssh_host,
                ssh_key_path=args.ssh_key_path,
                display_name=args.display_name,
            )
        )
    parser.error(f"unknown subcommand: {args.subcmd}")


if __name__ == "__main__":
    main()
