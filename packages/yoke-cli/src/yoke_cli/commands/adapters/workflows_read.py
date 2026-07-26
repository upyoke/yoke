"""``yoke workflows definition get`` adapter (read-only workflow definition).

Serves the registry's current immutable workflow definitions, gate placements,
and deployment flows (optionally scoped to one project).
"""

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


WORKFLOWS_DEFINITION_GET_USAGE = (
    "yoke workflows definition get [--project P] [--session-id S] [--json]"
)


def workflows_definition_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows definition get",
        description=WORKFLOWS_DEFINITION_GET_USAGE,
    )
    parser.add_argument("--project", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, WORKFLOWS_DEFINITION_GET_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(f"family|{result.get('family') or ''}", file=stdout)
        for workflow in result.get("workflows") or []:
            definition = workflow.get("definition") or {}
            stages = ",".join(
                str(stage.get("id") or "")
                for stage in definition.get("stages") or []
            )
            print(
                "workflow|" + "|".join(
                    str(value or "")
                    for value in (
                        workflow.get("id"),
                        workflow.get("current_version"),
                        workflow.get("current_version_id"),
                        workflow.get("status"),
                        stages,
                    )
                ),
                file=stdout,
            )
            for stage in definition.get("stages") or []:
                for gate in stage.get("gates") or []:
                    print(
                        f"gate|{workflow.get('id')}"
                        f"|{stage.get('id')}|{gate.get('id')}",
                        file=stdout,
                    )
        for gate in result.get("gate_catalog") or []:
            print(
                "catalog-gate|" + "|".join(
                    str(value or "")
                    for value in (
                        gate.get("id"),
                        gate.get("owner"),
                        gate.get("description"),
                    )
                ),
                file=stdout,
            )
        for flow in result.get("flows") or []:
            stage_names = ",".join(flow.get("stage_names") or [])
            print(
                "flow|" + "|".join(
                    "" if value is None else str(value)
                    for value in (
                        flow.get("id"), flow.get("name"),
                        flow.get("target_env"), flow.get("on_failure"),
                        stage_names, flow.get("project"),
                    )
                ),
                file=stdout,
            )
        return None

    payload: Dict[str, Any] = {}
    if parsed.project is not None:
        payload["project"] = parsed.project
    return dispatch_and_emit(
        function_id="workflows.definition.get",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["WORKFLOWS_DEFINITION_GET_USAGE", "workflows_definition_get"]
