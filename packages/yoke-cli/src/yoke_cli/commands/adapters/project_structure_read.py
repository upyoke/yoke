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


__all__ = [
    "PROJECT_STRUCTURE_DEPLOY_DEFAULTS_GET_USAGE",
    "project_structure_deploy_defaults_get",
]
