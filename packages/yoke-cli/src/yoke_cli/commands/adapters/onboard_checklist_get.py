"""Read scoped setup facts and verify the serving checklist contract."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from yoke_cli.commands._helpers import (
    client_project_context,
    parse_or_usage_error,
    ensure_handlers_loaded,
)
from yoke_cli.config import onboard_checklist_render, onboard_setup_facts
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_contracts.onboard_checklist import SCHEMA_VERSION

ONBOARD_CHECKLIST_GET_USAGE = (
    "yoke onboard checklist get [--project P] [--run-id RUN] "
    "[--config PATH] [--checkout PATH] [--json]"
)


def get_setup(payload: dict[str, Any], target: TargetRef) -> FunctionCallResponse:
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="onboard.checklist.get",
        target=target,
        actor=build_actor(),
        payload={
            key: value
            for key, value in payload.items()
            if key
            in {
                "project",
                "project_id",
                "run_id",
                "machine_id",
                "observations",
            }
        },
    )
    if (
        response.success
        and (response.result or {}).get("schema_version") != SCHEMA_VERSION
    ):
        response.success = False
        response.error = FunctionError(
            code="setup_facts_unavailable",
            message="Checklist schema 2 is required; ask the control-plane operator "
            "to provide a serving release with scoped setup facts.",
        )
    return response


def render_lookup(response: FunctionCallResponse, stdout, stderr) -> None:
    run = (response.result or {}).get("run")
    if run is None:
        print(
            "No saved setup run. Initialize it with yoke onboard checklist init --project P --checkout PATH.",
            file=stdout,
        )
    else:
        print(onboard_checklist_render.render_human(run), end="", file=stdout)


def onboard_checklist_get(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke onboard checklist get")
    parser.add_argument("--project", help="Project whose setup run to read.")
    parser.add_argument(
        "--run-id",
        help="Setup run id to read.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        help="Machine config file to read; default: the standard config path.",
    )
    parser.add_argument(
        "--checkout",
        dest="checkout_path",
        help="Project checkout to read setup facts from.",
    )
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Print JSON instead of text.",
    )
    parsed = parse_or_usage_error(parser, args, ONBOARD_CHECKLIST_GET_USAGE)
    if parsed is None:
        return 2
    from yoke_cli.config.project_onboard_support import machine_config_path

    with machine_config_path(parsed.config_path):
        try:
            payload = {
                "project": parsed.project,
                "run_id": parsed.run_id,
                **onboard_setup_facts.collect(
                    config_path=parsed.config_path,
                    checkout_path=parsed.checkout_path,
                ),
            }
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        response = get_setup(
            payload,
            TargetRef(
                kind="global",
                project_id=parsed.project or client_project_context(),
            ),
        )
        return emit_response(
            response, json_mode=parsed.json_mode, human_writer=render_lookup
        )
