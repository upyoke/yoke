"""One foreground command over short, stateless universe prune passes."""

import argparse
import sys

from yoke_cli.commands._helpers import (
    add_full_arg,
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.universe_retention_output import PruneRun, write_summary
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_cli.transport.relay_telemetry import TRANSPORT_FAILED_CODE
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)

GET_USAGE = "yoke universe retention get [--json]"
PRUNE_USAGE = "yoke universe prune [--dry-run | --apply] [--json]"


def _parser(prune):
    parser = argparse.ArgumentParser(
        prog="yoke universe prune" if prune else "yoke universe retention get",
        description=(
            "Preview disposable rows in the connected universe; --apply deletes eligible rows. "
            "Universe/org admin required. One run continues until a full cycle deletes nothing, "
            "using one fixed UTC cutoff and bounded transactions. It prints a progress line about "
            "every 10 seconds and a short summary: total deleted, tables that changed, duration, "
            "and any table not finished with its reason and recovery. Ctrl-C keeps committed "
            "batches and prints the same summary. Results are command output only; no saved "
            "prune audit or run record. No vacuum/analyze or physical file-shrink promise."
            if prune
            else "Read the selected universe's effective retention policy, source, digest and UTC cutoff. "
            "Universe/org admin required. Reads never seed or change settings; no editor ships."
        ),
    )
    if prune:
        modes = parser.add_mutually_exclusive_group()
        modes.add_argument(
            "--dry-run", action="store_true", help="Preview only (the default)."
        )
        modes.add_argument(
            "--apply",
            action="store_true",
            help="Delete eligible rows with the effective policy.",
        )
    add_session_arg(parser)
    add_json_arg(parser)
    add_full_arg(
        parser,
        "per-table eligible, deleted and protected detail plus the policy digest"
        if prune
        else "the complete policy",
    )
    return parser


def retention_get(args):
    parsed = parse_or_usage_error(_parser(False), args, GET_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="universe.retention.get",
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def _failure(code, message):
    return FunctionCallResponse(
        success=False,
        function="universe.prune.run",
        version="v1",
        request_id="",
        error=FunctionError(code=code, message=message),
    )


REQUIRED_FIELDS = (
    "universe",
    "source",
    "policy",
    "policy_digest",
    "cutoff",
    "next_table_index",
    "cycle_complete",
    "skipped",
)


def _finish(response, parsed, run):
    response = response.model_copy(
        update={"result": run.result("apply" if parsed.apply else "preview")}
    )
    if parsed.json_mode:
        return emit_response(response, json_mode=True)

    def summary(display, out, _err):
        write_summary(display.result, out, parsed.full)

    return emit_response(
        response, json_mode=False, human_writer=summary, failure_writer=summary
    )


def universe_prune(args):
    parsed = parse_or_usage_error(_parser(True), args, PRUNE_USAGE)
    if parsed is None:
        return 2
    ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    payload = {"apply": parsed.apply}
    run = PruneRun(parsed.apply)
    try:
        while True:
            # Never automatically retry an ambiguous mutating pass: no stored
            # receipt can turn a lost reply into an acknowledged exact count.
            response = call_dispatcher(
                function_id="universe.prune.run",
                target=TargetRef(kind="global"),
                actor=actor,
                payload=payload,
                max_attempts=1,
            )
            result = response.result or {}
            run.record(result)
            if response.success and not all(k in result for k in REQUIRED_FIELDS):
                return _finish(
                    _failure(
                        "retention_response_version_skew",
                        "Required prune response fields are absent (floor: next-release); counts above are what this pass reported. Recovery: ask the control-plane operator to serve the release carrying single-run universe prune, then rerun prune.",
                    ),
                    parsed,
                    run,
                )
            if not run.identity and result.get("universe"):
                run.identity = {
                    key: result[key]
                    for key in (
                        "universe",
                        "source",
                        "policy",
                        "policy_digest",
                        "cutoff",
                    )
                }
                if not parsed.json_mode:
                    print(
                        f"{'Pruning' if parsed.apply else 'Previewing'} universe {result['universe']['slug']} (cutoff {result['cutoff']})",
                        file=sys.stderr,
                        flush=True,
                    )
            if not response.success:
                if (
                    parsed.apply
                    and response.error
                    and response.error.code == TRANSPORT_FAILED_CODE
                ):
                    response = _failure(
                        "retention_pass_outcome_unknown",
                        f"{response.error.code}: {response.error.message}. The last pass was not acknowledged; its deletion count is unknown. Earlier acknowledged totals are shown. "
                        "Committed batches remain committed. Recovery: restore the connection/authority and rerun universe prune.",
                    )
                return _finish(response, parsed, run)
            if not parsed.json_mode:
                run.progress()
            if result["cycle_complete"] and not run.next_cycle():
                return _finish(response, parsed, run)
            payload = {
                "apply": parsed.apply,
                "cutoff": result["cutoff"],
                "expected_digest": result["policy_digest"],
                "table_index": result["next_table_index"],
            }
            if run.skip_tables:
                payload["skip_tables"] = run.skip_tables
    except KeyboardInterrupt:
        _finish(
            _failure(
                "retention_interrupted",
                "Interrupted; the active pass's outcome is unknown. Earlier acknowledged totals are shown; committed batches remain committed. Recovery: rerun universe prune.",
            ),
            parsed,
            run,
        )
        return 130


USAGE_BY_FUNCTION_ID = {
    "universe.retention.get": GET_USAGE,
    "universe.prune.run": PRUNE_USAGE,
}
