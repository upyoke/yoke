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
    parser.add_argument("project", help="Project ID (e.g. example-project)")
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
        "--pulumi-stack",
        help="Render one exact declared stack name with --only pulumi",
    )
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
    if args.pulumi_stack and args.only != "pulumi":
        parser.error("--pulumi-stack requires --only pulumi")
    settings_path = Path(args.settings_file).expanduser() if args.settings_file else None
    if settings_path is not None:
        payload = json.loads(settings_path.read_text())
        if payload.get("config_schema") == 2:
            _render_scoped_payload(parser, args, payload)
            return
    settings = (
        _load_settings_file(settings_path, args.project)
        if settings_path is not None
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
        pulumi_stack=args.pulumi_stack,
    )


def _render_scoped_payload(parser, args, payload) -> None:
    from .project_renderer import _resolve_project_root, default_render_output_dir
    from .project_renderer_pulumi_scoped import render_scoped_pulumi_config

    project = str(payload.get("project_slug") or "")
    stack = str(payload.get("stack_name") or "")
    if project != args.project:
        parser.error(
            f"--settings-file names project {project!r} but the render "
            f"targets {args.project!r}"
        )
    if args.only != "pulumi" or not args.write:
        parser.error("schema-v2 stack config requires --write --only pulumi")
    if args.pulumi_stack != stack:
        parser.error(
            "schema-v2 stack config requires --pulumi-stack to exactly match "
            "the payload stack"
        )
    output_dir = (
        Path(args.output_dir).expanduser()
        if args.output_dir
        else default_render_output_dir(project)
    )
    render_scoped_pulumi_config(
        payload,
        project_root=_resolve_project_root(),
        output_dir=output_dir,
    )


__all__ = ["main"]
