"""One foreground command over short, stateless universe prune passes."""

import argparse
from collections import Counter
import json
import sys
import time

from yoke_cli.commands._helpers import (
    add_full_arg,
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
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
            "Universe/org admin required. Runs in the foreground until finished, with bounded "
            "transactions and progress output. Committed batches survive interruption; rerun "
            "to select remaining eligible records. Results are command output only; no saved "
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
    add_full_arg(parser, "the complete policy and per-table result")
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


def _finish(response, parsed, deleted, tables, identity):
    result = dict(identity)
    result.update(
        mode="apply" if parsed.apply else "preview",
        deleted=dict(deleted),
        tables=list(tables.values()),
    )
    response = response.model_copy(update={"result": result})
    if parsed.json_mode:
        return emit_response(response, json_mode=True)
    for table, row in tables.items():
        eligible = (
            f">={row['eligible']} (bounded)"
            if row["eligible_partial"]
            else str(row["eligible"])
        )
        print(
            f"{table}: eligible={eligible}; deleted={deleted[table]}; protected>={row['protected']} (sample)"
        )
        if row.get("protected_graphs"):
            print(
                f"  retained graphs={row['protected_graphs']}: {row['graph_budget_reason']}"
            )
    print("Committed deletion totals: " + json.dumps(dict(deleted), sort_keys=True))
    if not parsed.apply:
        print(
            "Preview only; protected counts are bounded samples, not full-table totals."
        )
    return emit_response(response, json_mode=False, human_writer=lambda *_: None)


def universe_prune(args):
    parsed = parse_or_usage_error(_parser(True), args, PRUNE_USAGE)
    if parsed is None:
        return 2
    ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    payload = {"apply": parsed.apply}
    deleted, tables, identity = Counter(), {}, {}
    cycle_deleted = 0
    last_progress = time.monotonic()
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
            required = (
                "universe",
                "source",
                "policy",
                "policy_digest",
                "cutoff",
                "next_table_index",
                "cycle_complete",
            )
            if response.success and not all(key in result for key in required):
                return _finish(
                    _failure(
                        "retention_response_version_skew",
                        "Required prune response fields are absent (floor: next-release); this pass's outcome/count is unknown. Recovery: ask the control-plane operator to serve the release carrying universe retention, then rerun prune.",
                    ),
                    parsed,
                    deleted,
                    tables,
                    identity,
                )
            if not identity and result.get("universe"):
                identity = {
                    key: result[key]
                    for key in (
                        "universe",
                        "source",
                        "policy",
                        "policy_digest",
                        "cutoff",
                    )
                }
                print(
                    f"Universe {identity['universe']['slug']}; policy={identity['policy_digest']}; cutoff={identity['cutoff']}",
                    file=sys.stderr,
                    flush=True,
                )
            for row in result.get("tables", []):
                tables[row["table"]] = row
                deleted.update(row["deleted"])
                cycle_deleted += sum(row["deleted"].values())
            if not response.success:
                if (
                    parsed.apply
                    and response.error
                    and response.error.code == TRANSPORT_FAILED_CODE
                ):
                    response = _failure(
                        "retention_pass_outcome_unknown",
                        f"{response.error.code}: {response.error.message}. The last pass was not acknowledged; its deletion count is unknown. Earlier acknowledged totals follow. "
                        "Committed batches remain committed. Recovery: restore the connection/authority and rerun universe prune.",
                    )
                return _finish(response, parsed, deleted, tables, identity)
            if time.monotonic() - last_progress >= 5:
                print(
                    f"Prune progress: committed rows={sum(deleted.values())}; tables visited={len(tables)}",
                    file=sys.stderr,
                    flush=True,
                )
                last_progress = time.monotonic()
            if result["cycle_complete"]:
                if not parsed.apply or cycle_deleted == 0:
                    return _finish(response, parsed, deleted, tables, identity)
                cycle_deleted = 0
            payload = {
                "apply": parsed.apply,
                "cutoff": result["cutoff"],
                "expected_digest": result["policy_digest"],
                "table_index": result["next_table_index"],
            }
    except KeyboardInterrupt:
        result = _failure(
            "retention_interrupted",
            "Interrupted; the active pass's outcome is unknown. Earlier acknowledged totals follow; committed batches remain committed. Recovery: rerun universe prune.",
        )
        _finish(result, parsed, deleted, tables, identity)
        return 130


USAGE_BY_FUNCTION_ID = {
    "universe.retention.get": GET_USAGE,
    "universe.prune.run": PRUNE_USAGE,
}
