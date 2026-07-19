"""Project-owned deployment-flow reconciliation CLI adapter."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.project_install.deployment_flows import load_declaration
from yoke_cli.project_install.files import ProjectInstallError
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.project_contract.deployment_flows import (
    DECLARATION_RELATIVE_PATH,
)


USAGE = (
    "yoke deployment-flows reconcile-project PROJECT [DECLARATION-FILE] "
    "[--preview] [--session-id S] [--json]"
)


def deployment_flows_reconcile_project(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-flows reconcile-project",
        description=(
            "Additively reconcile a project-owned deployment-flow declaration. "
            "Omitted and historically referenced definitions are preserved."
        ),
    )
    parser.add_argument("project")
    parser.add_argument(
        "declaration_file",
        nargs="?",
        default=DECLARATION_RELATIVE_PATH,
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Validate and show the reconciliation result without DB writes.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, USAGE)
    if parsed is None:
        return 2
    try:
        declaration = load_declaration(Path(parsed.declaration_file))
    except ProjectInstallError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        print(
            "|".join(
                (
                    str(result.get("project") or ""),
                    f"created={len(result.get('created') or [])}",
                    f"updated={len(result.get('updated') or [])}",
                    f"unchanged={len(result.get('unchanged') or [])}",
                )
            ),
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="deployment_flows.reconcile_project",
        target=TargetRef(kind="global", project_id=parsed.project),
        payload=declaration,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
        options={"preview_only": True} if parsed.preview else None,
    )


__all__ = ["deployment_flows_reconcile_project"]
