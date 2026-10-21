"""Field-selected deployment-run reads and bounded CLI summary pages."""

from __future__ import annotations

import argparse
from typing import List
from yoke_cli.transport.human_values import write_human
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_full_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef, FunctionError

DEPLOYMENT_RUNS_GET_USAGE = "yoke deployment-runs get RUN-ID [FIELD ...] [--full] [--include-member-closure] [--session-id S] [--json]"
DEPLOYMENT_RUNS_LIST_USAGE = (
    "yoke deployment-runs list [--project P] [--status STATUS] "
    "[--relevance overview] [--limit N] [--cursor CURSOR] [--session-id S] [--json]"
)


#: Server-computed get fields; an older server refuses them as invalid_field.
COMPUTED_RUN_FIELDS = ("member_items", "membership_removals")


def _floor_refusal(response, message):
    return response.model_copy(
        update={
            "success": False,
            "result": None,
            "error": FunctionError(
                code="deployment_run_read_projection_unavailable", message=message
            ),
        }
    )


def _require_projection(expected_fields=None, summary=False, requested=()):
    def validate(response, _actor):
        computed = [name for name in requested if name in COMPUTED_RUN_FIELDS]
        if (
            not response.success
            and computed
            and response.error is not None
            and response.error.code == "invalid_field"
        ):
            return _floor_refusal(
                response,
                f"Serving floor: computed run fields ({', '.join(computed)}). "
                "Ask the control-plane operator to install a release carrying "
                "them; until then read members with `yoke deployment-runs list "
                "--relevance overview --json`.",
            )
        if not response.success:
            return response
        result = response.result or {}
        valid = (
            (
                result.get("fields") == list(dict.fromkeys(expected_fields))
                and set(result.get("run") or {}) == set(expected_fields)
            )
            if expected_fields
            else ("detail_recipe" in result if summary else True)
        )
        if valid:
            return response
        return _floor_refusal(
            response,
            "Serving floor: deployment-run field selection and summary pagination. "
            "Ask the control-plane operator to install a release carrying this read contract; "
            "use get RUN-ID FIELD for individual fields meanwhile.",
        )

    return validate


def deployment_runs_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs get",
        description=DEPLOYMENT_RUNS_GET_USAGE
        + " Defaults to a bounded run and membership summary; select FIELD ... for detail or --full for the whole run. Computed fields: member_items (attached members, removed ones"
        " excluded) and membership_removals (reason, removed_at, later_run_id)."
        " carried_work is recorded at composition freeze; before that get"
        " derives it live and it stays unrecorded.",
    )
    parser.add_argument("run_id")
    parser.add_argument(
        "fields",
        nargs="*",
        help="Return only these row or computed fields.",
    )
    parser.add_argument(
        "--include-member-closure",
        action="store_true",
        help="Read expensive per-member settlement diagnostics explicitly.",
    )
    add_full_arg(parser, "the complete run and membership detail")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_RUNS_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        from yoke_cli.commands.adapters.deployment_run_output import write_run_summary

        if parsed.fields or parsed.full or parsed.include_member_closure:
            write_human(response.result, stdout)
        else:
            write_run_summary(response.result or {}, stdout)

    return dispatch_and_emit(
        function_id="deployment_runs.get",
        target=TargetRef(kind="workflow_run", workflow_run_id=parsed.run_id),
        payload={
            **(
                {"fields": parsed.fields}
                if len(parsed.fields) > 1
                else {"field": next(iter(parsed.fields), None)}
            ),
            **(
                {"include_member_closure": True}
                if parsed.include_member_closure
                else {}
            ),
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
        response_recovery=_require_projection(
            parsed.fields if len(parsed.fields) > 1 else None,
            requested=parsed.fields,
        ),
    )


def deployment_runs_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs list",
        description=DEPLOYMENT_RUNS_LIST_USAGE
        + " Defaults to 20 summary rows; use next_cursor with --cursor to continue. Read full row fields with get RUN-ID FIELD ... .",
    )
    parser.add_argument("--project", default=None)
    parser.add_argument("--status", default=None)
    parser.add_argument(
        "--relevance",
        choices=["overview"],
        default=None,
        help="Shipping's live/recent runs with member QA and delivery facts.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of recent runs to return.",
    )
    parser.add_argument("--cursor", help="Continue the summary page using next_cursor.")
    add_full_arg(parser, "all returned summary columns")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_RUNS_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        if parsed.full or parsed.relevance:
            write_human(result, stdout)
            return
        rows = result.get("rows") or []
        write_human(
            {
                "runs": [
                    {
                        key: row[key]
                        for key in (
                            "id",
                            "project",
                            "target_environment",
                            "status",
                            "current_stage",
                        )
                        if key in row
                    }
                    for row in rows
                ]
            },
            stdout,
        )
        if result.get("next_cursor"):
            print(
                f"Next page: yoke deployment-runs list --project {parsed.project or 'P'} --cursor {result['next_cursor']}",
                file=stdout,
            )
        print(
            "More columns: --full; one run: yoke deployment-runs get RUN-ID FIELD ...",
            file=stdout,
        )

    if parsed.cursor and parsed.relevance:
        parser.error("--cursor cannot combine with --relevance; remove one")
    payload = {"summary": True} if parsed.relevance is None else {}
    if parsed.cursor is not None:
        payload["cursor"] = parsed.cursor
    if parsed.project is not None:
        payload["project"] = parsed.project
    if parsed.status is not None:
        payload["status"] = parsed.status
    if parsed.relevance is not None:
        payload["relevance"] = parsed.relevance
    if parsed.limit is not None:
        payload["limit"] = parsed.limit
    return dispatch_and_emit(
        function_id="deployment_runs.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
        response_recovery=_require_projection(summary=parsed.relevance is None),
    )
