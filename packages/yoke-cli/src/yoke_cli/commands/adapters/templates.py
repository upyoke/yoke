"""Template adapters for the ``yoke`` CLI.

``yoke templates list`` / ``yoke templates fetch`` discover and pull
raw template material (``templates/<name>/**`` with ``{{placeholders}}``
intact) from the CLI's active env. Sibling
of :mod:`yoke_cli.commands.adapters.install`: the domain functions run
in-process on this machine (the destination dir lives here), printing
the report; the active env's transport decides https-GET vs in-process
build. Env selection rides the CLI's global ``--env`` flag.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_cli.commands._helpers import (
    attach_field_note_footer,
    parse_or_usage_error,
)
from yoke_cli.config import template_fetch


TEMPLATES_LIST_USAGE = "yoke templates list [--json] [--config PATH]"
TEMPLATES_FETCH_USAGE = (
    "yoke templates fetch NAME [--dest DIR] [--only SUBPATH] "
    "[--force] [--source-dev-admin] [--config PATH]"
)

_LIST_HELP = """\
Discover the served templates (name, description, file count). An https
env GETs the listing from the env's server; a non-prod local env serves
it in-process from this install's code tree.

Example:
  yoke templates list
"""

_FETCH_HELP = """\
Fetch one template's files RAW ({{placeholders}} intact) into --dest
(default: cwd). An https env GETs the bundle from the env's server; a
non-prod local env builds it in-process from this install's code tree.
Existing files are skipped and reported unless --force.
Templates marked source-dev/admin require the explicit --source-dev-admin
opt-in and should only be fetched from an operator-approved flow.

Example:
  yoke templates fetch NAME --dest scratch/template-material
"""


def templates_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke templates list",
        description=_LIST_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", dest="json_mode", action="store_true",
                        help="Emit the listing as JSON.")
    parser.add_argument("--config", dest="config_path", default=None)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, TEMPLATES_LIST_USAGE)
    if parsed is None:
        return 2
    try:
        templates, source = template_fetch.resolve_listing(parsed.config_path)
    except template_fetch.TemplateFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps({"templates": templates, "source": source}, indent=2))
        return 0
    for entry in templates:
        description = str(entry.get("description") or "").strip()
        suffix = f" — {description}" if description else ""
        print(f"{entry.get('name')} ({entry.get('file_count')} files){suffix}")
    return 0


def templates_fetch(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke templates fetch",
        description=_FETCH_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("name", help="Template name from `yoke templates list`.")
    parser.add_argument("--dest", default=None,
                        help="Destination dir for the files (default: cwd).")
    parser.add_argument("--only", default=None,
                        help="Keep only bundle paths with this prefix, e.g. ops/.")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing files instead of skipping them.")
    parser.add_argument(
        "--source-dev-admin",
        action="store_true",
        help="Allow fetching templates marked source-dev/admin.",
    )
    parser.add_argument("--config", dest="config_path", default=None)
    attach_field_note_footer(parser)
    parsed = parse_or_usage_error(parser, args, TEMPLATES_FETCH_USAGE)
    if parsed is None:
        return 2
    try:
        report = template_fetch.fetch(
            parsed.name,
            parsed.dest,
            only=parsed.only,
            force=parsed.force,
            config_path=parsed.config_path,
            include_source_dev_admin=parsed.source_dev_admin,
        )
    except template_fetch.TemplateFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0

__all__ = [
    "TEMPLATES_FETCH_USAGE",
    "TEMPLATES_LIST_USAGE",
    "templates_fetch",
    "templates_list",
]
