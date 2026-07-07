"""Validate a webapp end-to-end pipeline's prerequisites for a given project.

Runs pre-flight checks covering database state, the local project repository,
GitHub Actions, Yoke pipeline entrypoints, deployment flow readiness, and
optional SSH connectivity. The project identifier is supplied at call time
(via ``ValidateContext.project`` or the ``--project`` CLI flag); no project
identity is hardcoded here. Exits with ``0`` on success or ``1`` on any
failure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .validate_webapp_pipeline_checks_db import (
    _check_database_prerequisites,  # noqa: F401
    _check_local_repository,  # noqa: F401
)
from .validate_webapp_pipeline_checks_remote import (
    _check_deployment_flow_readiness,  # noqa: F401
    _check_github_actions_infrastructure,  # noqa: F401
    _check_pipeline_scripts,  # noqa: F401
    _check_ssh_connectivity,  # noqa: F401
)
from .validate_webapp_pipeline_helpers import (
    Counters,  # noqa: F401
    ValidateContext,
    _capability_secret,  # noqa: F401
    _capability_settings,  # noqa: F401
    _check_fail,  # noqa: F401
    _check_pass,  # noqa: F401
    _check_warn,  # noqa: F401
    _run,  # noqa: F401
    _which,  # noqa: F401
)


def _print_summary(counters: Counters) -> int:
    print("\n=== Summary ===\n")
    print(f"Total checks: {counters.total}")
    print(f"  Passed: {counters.passed}")
    print(f"  Failed: {counters.failed}")
    print(f"  Warnings: {counters.warned}")

    if counters.failed > 0:
        print(
            f"\nPre-flight FAILED -- resolve {counters.failed} failure(s) before running the pipeline."
        )
        return 1

    if counters.warned > 0:
        print(
            f"\nPre-flight PASSED with {counters.warned} warning(s). Pipeline may work but review warnings."
        )
    else:
        print("\nPre-flight PASSED. All prerequisites are in place.")
    print(
        "Next step: /yoke idea to file the project item, then follow the validation runbook."
    )
    return 0


def run_validation(ctx: ValidateContext) -> int:
    counters = Counters()

    repo_path, github_repo = _check_database_prerequisites(ctx, counters)
    _check_local_repository(ctx, counters, repo_path)
    _check_github_actions_infrastructure(ctx, counters, repo_path, github_repo)
    _check_pipeline_scripts(ctx, counters)
    _check_deployment_flow_readiness(ctx, counters)
    _check_ssh_connectivity(ctx, counters)

    return _print_summary(counters)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate-webapp-pipeline",
        description="Python owner for webapp pipeline pre-flight validation",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--project",
        required=True,
        help="Project slug or numeric id in the Yoke DB.",
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--script-dir", required=True)
    parser.add_argument(
        "--yoke-db",
        dest="control_plane_marker",
        required=True,
        help=(
            "Legacy path-shaped control-plane marker; Yoke authority is "
            "resolved by the backend factory."
        ),
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    ctx = ValidateContext(
        project_root=Path(args.project_root),
        script_dir=Path(args.script_dir),
        control_plane_marker=Path(args.control_plane_marker),
        project=args.project,
        verbose=args.verbose,
    )
    sys.exit(run_validation(ctx))


if __name__ == "__main__":
    main()
