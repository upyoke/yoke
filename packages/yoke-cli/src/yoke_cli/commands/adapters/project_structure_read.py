"""``yoke project-structure deploy-defaults ...`` read adapter."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.transport.human_values import write_human


PROJECT_STRUCTURE_DEPLOY_DEFAULTS_GET_USAGE = (
    "yoke project-structure deploy-defaults get --project NAME "
    "[--session-id S] [--json]"
)

_DEPLOY_DEFAULTS_GET_HELP_DEEP = """\
Read the configured project default deployment flow. A labeled empty value
means the project has no default flow configured.

Worked example:

  yoke project-structure deploy-defaults get --project yoke

Flag matrix:

  flag          required  value shape
  --project     yes       project slug or id
  --session-id  no        opaque session id (operator-debug)
  --json        no        flag (typed envelope on stdout)

Exit codes: 0 success, 1 dispatch failure, 2 usage error.
"""


def project_structure_deploy_defaults_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke project-structure deploy-defaults get",
        usage=PROJECT_STRUCTURE_DEPLOY_DEFAULTS_GET_USAGE,
        description=_DEPLOY_DEFAULTS_GET_HELP_DEEP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        PROJECT_STRUCTURE_DEPLOY_DEFAULTS_GET_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, _stderr) -> None:
        write_human(response.result, stdout)

    return dispatch_and_emit(
        function_id="project_structure.deploy_defaults.get",
        target=TargetRef(
            kind="project_structure",
            project_id=parsed.project,
        ),
        payload={"project_id": parsed.project},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


PROJECT_STRUCTURE_GET_USAGE = (
    "yoke project-structure get --project NAME [--family F] [--session-id S] [--json]"
)

_GET_HELP_DEEP = """\
Read the Project Structure tree, or one family slice.

Worked example:

  yoke project-structure get --project platform --family test_roots

Flag matrix:

  flag          required  value shape
  --project     yes       project slug or id
  --family      no        family id (omit for the whole tree)
  --session-id  no        opaque session id (operator-debug)
  --json        no        flag (typed envelope on stdout)

Exit codes: 0 success, 1 dispatch failure, 2 usage error.
"""


def project_structure_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke project-structure get",
        usage=PROJECT_STRUCTURE_GET_USAGE,
        description=_GET_HELP_DEEP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    parser.add_argument("--family", default=None, help="Optional family slice.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PROJECT_STRUCTURE_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, _stderr) -> None:
        write_human(response.result, stdout)

    payload: Dict[str, Any] = {"project_id": parsed.project}
    if parsed.family:
        payload["family"] = parsed.family
    return dispatch_and_emit(
        function_id="project_structure.get",
        target=TargetRef(kind="project_structure", project_id=parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


ARCHITECTURE_HEALTH_GET_USAGE = (
    "yoke project-structure architecture-health get --project NAME "
    "[--session-id S] [--json]"
)

_ARCHITECTURE_HEALTH_HELP_DEEP = """\
Coverage and violations for the project's declared architecture map:
classified / exempt / unclassified Python paths, forbidden dependency
edges, and guarded-import violations. `declared: false` means the
project has no map yet — propose one with
`yoke project-structure architecture-draft get`.

Worked example:

  yoke project-structure architecture-health get --project yoke

Exit codes: 0 success, 1 dispatch failure, 2 usage error.
"""


def architecture_health_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke project-structure architecture-health get",
        usage=ARCHITECTURE_HEALTH_GET_USAGE,
        description=_ARCHITECTURE_HEALTH_HELP_DEEP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ARCHITECTURE_HEALTH_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, _stderr) -> None:
        health: Dict[str, Any] = (response.result or {}).get("health") or {}
        if not health.get("declared"):
            stdout.write("architecture map: not declared\n")
            return None
        stdout.write(
            f"coverage: {health.get('coverage_pct')}% "
            f"({health.get('classified')} classified, "
            f"{health.get('exempt')} exempt, "
            f"{health.get('unclassified')} unclassified "
            f"of {health.get('python_paths')} python paths)\n"
        )
        stdout.write(
            f"violations: {health.get('forbidden_edge_count')} forbidden "
            f"edge(s), {health.get('cross_cutting_count')} guarded-import\n"
        )
        for example in health.get("forbidden_edge_examples") or []:
            stdout.write(
                f"  edge {example.get('path')}: "
                f"{example.get('source_layer')} → "
                f"{example.get('imported_layer')} via "
                f"{example.get('imported_module')}\n"
            )
        for example in health.get("cross_cutting_examples") or []:
            stdout.write(
                f"  import {example.get('path')}: "
                f"{example.get('guarded_symbol')} outside "
                f"'{example.get('entrypoint')}'\n"
            )
        return None

    return dispatch_and_emit(
        function_id="project_structure.architecture_health.get",
        target=TargetRef(kind="project_structure", project_id=parsed.project),
        payload={"project_id": parsed.project},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


ARCHITECTURE_DRAFT_GET_USAGE = (
    "yoke project-structure architecture-draft get --project NAME "
    "[--session-id S] [--json]"
)

_ARCHITECTURE_DRAFT_HELP_DEEP = """\
Propose a draft architecture map from the project's latest path
snapshot: areas from directory structure, kinds from naming
conventions, tests exempted, guesses disclosed as notes. Review and
edit the payload, then apply it with
`yoke project-structure patch apply` (family architecture_model).
An empty tree proposes the minimal map (layer vocabulary only).

Worked example (draft to a file for review):

  yoke project-structure architecture-draft get --project myapp --json \\
    > /tmp/architecture-draft.json

Exit codes: 0 success, 1 dispatch failure, 2 usage error.
"""


def architecture_draft_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke project-structure architecture-draft get",
        usage=ARCHITECTURE_DRAFT_GET_USAGE,
        description=_ARCHITECTURE_DRAFT_HELP_DEEP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ARCHITECTURE_DRAFT_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result, stdout)

    return dispatch_and_emit(
        function_id="project_structure.architecture_draft.get",
        target=TargetRef(kind="project_structure", project_id=parsed.project),
        payload={"project_id": parsed.project},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


# Usage strings for the read family, spliced into the aggregate
# adapter-usage map keyed by function id.
PROJECT_STRUCTURE_READ_USAGE = {
    "project_structure.deploy_defaults.get": PROJECT_STRUCTURE_DEPLOY_DEFAULTS_GET_USAGE,
    "project_structure.get": PROJECT_STRUCTURE_GET_USAGE,
    "project_structure.architecture_health.get": ARCHITECTURE_HEALTH_GET_USAGE,
    "project_structure.architecture_draft.get": ARCHITECTURE_DRAFT_GET_USAGE,
}


__all__ = [
    "ARCHITECTURE_DRAFT_GET_USAGE",
    "ARCHITECTURE_HEALTH_GET_USAGE",
    "PROJECT_STRUCTURE_DEPLOY_DEFAULTS_GET_USAGE",
    "PROJECT_STRUCTURE_GET_USAGE",
    "PROJECT_STRUCTURE_READ_USAGE",
    "architecture_draft_get",
    "architecture_health_get",
    "project_structure_deploy_defaults_get",
    "project_structure_get",
]
