"""CLI argument handling for the project template renderer.

``yoke_core.tools.render_project`` delegates here via
``project_renderer.main``. ``--settings-file`` feeds the body of
``GET /v1/projects/{project}/pulumi-stack-config`` straight into the
render so CI runners never need a database credential.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from . import project_renderer


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="project-renderer",
        description="Generate ops artifacts for a project from templates",
    )
    parser.add_argument("project", help="Project ID (e.g. buzz)")
    parser.add_argument("--write", action="store_true",
                        help="Save artifacts to output locations (default: stdout)")
    parser.add_argument(
        "--output-dir",
        help="Directory for --write output (default: scratch-backed project render storage)",
    )
    parser.add_argument("--only", default="all",
                        choices=["all", "DEPLOY.md", "DEPLOY-checklist.md", "RECOVERY.md", "workflows", "scaffold", "ops", "pulumi"],
                        help="Filter artifact types to render")
    parser.add_argument(
        "--settings-file",
        help=(
            "Render from a pulumi-stack-config payload (the body of "
            "GET /v1/projects/{project}/pulumi-stack-config) instead of "
            "reading the database"
        ),
    )
    return parser


def _load_settings_file(path: Path, project: str):
    """Parse a stack-config payload file and verify it names *project*."""
    from .project_renderer_settings_snapshot import settings_from_stack_config

    payload = json.loads(path.read_text())
    settings = settings_from_stack_config(payload)
    if settings.project != project:
        raise SystemExit(
            f"--settings-file names project {settings.project!r} "
            f"but the render targets {project!r}"
        )
    return settings


def main(argv: Optional[List[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = (
        _load_settings_file(Path(args.settings_file).expanduser(), args.project)
        if args.settings_file
        else None
    )
    # Resolve render_project through the module attribute so test patches
    # against ``project_renderer.render_project`` take effect.
    project_renderer.render_project(
        args.project,
        write=args.write,
        only=args.only,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        settings=settings,
    )


__all__ = ["main"]
