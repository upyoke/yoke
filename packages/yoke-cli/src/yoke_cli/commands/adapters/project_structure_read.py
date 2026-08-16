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


PROJECT_STRUCTURE_DEPLOY_DEFAULTS_GET_USAGE = (
    "yoke project-structure deploy-defaults get --project NAME "
    "[--session-id S] [--json]"
)

_DEPLOY_DEFAULTS_GET_HELP_DEEP = """\
Read the configured project default deployment flow. Empty stdout with exit 0
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
        description=(
            f"{PROJECT_STRUCTURE_DEPLOY_DEFAULTS_GET_USAGE}\n\n"
            f"{_DEPLOY_DEFAULTS_GET_HELP_DEEP}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, PROJECT_STRUCTURE_DEPLOY_DEFAULTS_GET_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, _stderr) -> None:
        result: Dict[str, Any] = response.result or {}
        flow = result.get("deployment_flow")
        if flow is None:
            return None
        text = str(flow)
        if not text:
            return None
        stdout.write(text)
        if not text.endswith("\n"):
            stdout.write("\n")
        return None

    return dispatch_and_emit(
        function_id="project_structure.deploy_defaults.get",
        target=TargetRef(
            kind="project_structure",
            project_id=parsed.project,
        ),
        payload={"project_id": parsed.project},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


PROJECT_STRUCTURE_GET_USAGE = (
    "yoke project-structure get --project NAME [--family F] "
    "[--session-id S] [--json]"
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
        description=f"{PROJECT_STRUCTURE_GET_USAGE}\n\n{_GET_HELP_DEEP}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    parser.add_argument("--family", default=None, help="Optional family slice.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PROJECT_STRUCTURE_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, _stderr) -> None:
        result: Dict[str, Any] = response.result or {}
        family = result.get("family")
        if family is not None:
            for entry in result.get("entries") or []:
                stdout.write(f"{entry.get('attachment', '')}\n")
            return None
        for name, entries in (result.get("families") or {}).items():
            for entry in entries or []:
                stdout.write(f"{name}\t{entry.get('attachment', '')}\n")
        return None

    payload: Dict[str, Any] = {"project_id": parsed.project}
    if parsed.family:
        payload["family"] = parsed.family
    return dispatch_and_emit(
        function_id="project_structure.get",
        target=TargetRef(kind="project_structure", project_id=parsed.project),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "PROJECT_STRUCTURE_DEPLOY_DEFAULTS_GET_USAGE",
    "PROJECT_STRUCTURE_GET_USAGE",
    "project_structure_deploy_defaults_get",
    "project_structure_get",
]
