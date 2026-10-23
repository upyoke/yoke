"""CLI adapters for the ``claims.coordination_claim.*`` family."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.coordination_claim_recovery import OPERATOR_RELEASE_USAGE
from yoke_contracts.coordination_claim_keys import QA_HOST_KEY_PREFIX


CLAIMS_COORDINATION_CLAIM_LIST_USAGE = (
    "yoke coordination-claim list [--project P] "
    "[--key K] [--session-id S] [--item PREFIX-N] [--active-only] [--full] [--json]"
)
CLAIMS_COORDINATION_CLAIM_ACQUIRE_USAGE = (
    "yoke claims coordination-claim acquire --project P --key K "
    "[--reason TEXT] [--item PREFIX-N] [--json]"
)
CLAIMS_COORDINATION_CLAIM_RELEASE_USAGE = (
    "yoke claims coordination-claim release (--project P --key K | "
    "--claim-id N) --reason TEXT [--json]"
)


def _print_claims(response: Any, stdout, _stderr) -> None:
    claims = (response.result or {}).get("claims") or []
    if not claims:
        print("no coordination claims", file=stdout)
        return
    print(
        "key\ttarget_kind\towner\tclaimed_at\treleased_at",
        file=stdout,
    )
    for claim in claims:
        owner = (
            f"item:{claim.get('owner_public_ref')}"
            if claim.get("owner_public_ref") is not None
            else (claim.get("session_id") or "")
        )
        print(
            f"{claim.get('key', '')}\t"
            f"{claim.get('target_kind', '')}\t"
            f"{owner}\t"
            f"{claim.get('claimed_at', '')}\t"
            f"{claim.get('released_at') or ''}",
            file=stdout,
        )


def _print_claim(response: Any, stdout, _stderr) -> None:
    claim = (response.result or {}).get("claim") or {}
    print(
        f"{claim.get('key', '')}\t"
        f"claim_id={claim.get('id', '')}\t"
        f"session={claim.get('session_id', '')}\t"
        f"claimed_at={claim.get('claimed_at', '')}\t"
        f"released_at={claim.get('released_at') or ''}",
        file=stdout,
    )


def claims_coordination_claim_acquire(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims coordination-claim acquire",
        usage=CLAIMS_COORDINATION_CLAIM_ACQUIRE_USAGE,
        epilog=(
            "Takes one shared-operation claim for this session. Deployment "
            "runs take none: a run occupies its target servers until its QA "
            "settles, or until a newer run on its flow and target takes it "
            "over while it waits only on item QA. Reserved qualification grants open only through "
            "session-control. A refused QA_HOST:<machine> acquire joins that "
            "host's waiting line and names its place; the next release "
            "reserves the host for the oldest live waiter and wakes it to "
            "rerun this same command, which takes the reserved turn."
        ),
    )
    parser.add_argument(
        "--project", required=True, metavar="P", help="Project slug or id."
    )
    parser.add_argument("--key", required=True, metavar="K", help="Coordination key.")
    parser.add_argument(
        "--reason",
        default=None,
        metavar="TEXT",
        help="Why this session is taking the claim.",
    )
    parser.add_argument(
        "--item",
        default=None,
        metavar="PREFIX-N",
        help="Item that owns the claim, for key kinds that record one.",
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        CLAIMS_COORDINATION_CLAIM_ACQUIRE_USAGE,
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"project_id": parsed.project, "key": parsed.key}
    if parsed.reason:
        payload["reason"] = parsed.reason
    if parsed.item:
        payload["public_ref"] = parsed.item
    return dispatch_and_emit(
        function_id="claims.coordination_claim.acquire",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_claim,
    )


def claims_coordination_claim_release(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims coordination-claim release",
        usage=CLAIMS_COORDINATION_CLAIM_RELEASE_USAGE,
        epilog=(
            "Releases a claim by the (project, key) that addresses it, or by "
            "row id. This is the holder's own release; freeing a claim "
            "stranded by another session is the steering-seat "
            "`yoke coordination-claim release`, which records an "
            "OperatorLeaseRelease event. Releasing a QA_HOST:<machine> claim "
            "reserves the host for the oldest live waiter in its line and "
            "wakes that session; releasing a reserved turn you no longer "
            "need passes it on."
        ),
    )
    parser.add_argument("--project", default=None, metavar="P", help="Project slug or id.")
    parser.add_argument("--key", default=None, metavar="K", help="Coordination key.")
    parser.add_argument(
        "--claim-id", type=int, default=None, metavar="N", help="The claim's id."
    )
    parser.add_argument(
        "--reason", required=True, metavar="TEXT", help="Why the claim is released."
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        CLAIMS_COORDINATION_CLAIM_RELEASE_USAGE,
    )
    if parsed is None:
        return 2
    if parsed.claim_id is None and not (parsed.project and parsed.key):
        print(f"usage: {CLAIMS_COORDINATION_CLAIM_RELEASE_USAGE}")
        return 2
    payload: Dict[str, Any] = {"reason": parsed.reason}
    if parsed.claim_id is not None:
        payload["claim_id"] = parsed.claim_id
    else:
        payload["project_id"] = parsed.project
        payload["key"] = parsed.key
    return dispatch_and_emit(
        function_id="claims.coordination_claim.release",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_claim,
    )


def claims_coordination_claim_operator_release(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke coordination-claim release",
        usage=OPERATOR_RELEASE_USAGE,
        epilog=(
            "Operator recovery for a claim stranded by another session. "
            "Run it from a session holding a live steering seat on the "
            "claim's project (yoke claims steering acquire --project P); "
            "other sessions are refused with steering_seat_required. Read the "
            "active row with `yoke "
            "coordination-claim list [--project P] --key K --active-only "
            "--json`, then pass its exact claim id and holder session. The "
            "command works through HTTPS or local authority, requires "
            "claims.release permission on the claim holder's project. "
            "QA_HOST:<machine> is machine-scoped: omit --project for list "
            "and operator release; other key kinds require it for release. "
            "The command records the reason, "
            "and refuses if the holder changed after review."
        ),
    )
    parser.add_argument(
        "--project",
        default=None,
        metavar="P",
        help="Project slug or id; omit for QA_HOST keys.",
    )
    parser.add_argument("--key", required=True, metavar="K", help="Coordination key.")
    parser.add_argument(
        "--claim-id",
        required=True,
        type=int,
        metavar="N",
        help="Id of the active claim you reviewed.",
    )
    parser.add_argument(
        "--holder-session-id",
        required=True,
        metavar="S",
        help="Session id of the claim's holder, as you reviewed it.",
    )
    parser.add_argument(
        "--reason", required=True, metavar="R", help="Why you are releasing it; recorded."
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, OPERATOR_RELEASE_USAGE)
    if parsed is None:
        return 2
    if not parsed.project and not parsed.key.startswith(QA_HOST_KEY_PREFIX):
        return usage_error("the following arguments are required: --project")
    return dispatch_and_emit(
        function_id="claims.coordination_claim.operator_release",
        target=TargetRef(kind="global"),
        payload={
            "project_id": parsed.project,
            "key": parsed.key,
            "claim_id": parsed.claim_id,
            "holder_session_id": parsed.holder_session_id,
            "reason": parsed.reason,
        },
        session_id=None,
        json_mode=parsed.json_mode,
    )


def claims_coordination_claim_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke coordination-claim list",
        usage=CLAIMS_COORDINATION_CLAIM_LIST_USAGE,
        epilog="QA_HOST:<machine> keys are machine-scoped; --project does not filter them.",
    )
    parser.add_argument("--project", default=None, metavar="P", help="Project slug or id.")
    parser.add_argument(
        "--key", default=None, metavar="K", help="Filter to one coordination key."
    )
    parser.add_argument(
        "--session-id",
        default=None,
        metavar="S",
        help="Filter to claims held by this session.",
    )
    parser.add_argument(
        "--item",
        default=None,
        metavar="PREFIX-N",
        help="Filter to claims owned by this item.",
    )
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Restrict to claims that have not been released.",
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        CLAIMS_COORDINATION_CLAIM_LIST_USAGE,
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.project:
        payload["project_id"] = parsed.project
    if parsed.key:
        payload["key"] = parsed.key
    if parsed.session_id:
        payload["session_id"] = parsed.session_id
    if parsed.item:
        payload["owner_public_ref"] = parsed.item
    if parsed.active_only:
        payload["active_only"] = True
    return dispatch_and_emit(
        function_id="claims.coordination_claim.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_claims,
    )


USAGE_BY_FUNCTION_ID = {
    "claims.coordination_claim.acquire": (CLAIMS_COORDINATION_CLAIM_ACQUIRE_USAGE),
    "claims.coordination_claim.list": CLAIMS_COORDINATION_CLAIM_LIST_USAGE,
    "claims.coordination_claim.release": (CLAIMS_COORDINATION_CLAIM_RELEASE_USAGE),
    "claims.coordination_claim.operator_release": OPERATOR_RELEASE_USAGE,
}

__all__ = [
    "CLAIMS_COORDINATION_CLAIM_ACQUIRE_USAGE",
    "CLAIMS_COORDINATION_CLAIM_LIST_USAGE",
    "CLAIMS_COORDINATION_CLAIM_RELEASE_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "claims_coordination_claim_acquire",
    "claims_coordination_claim_list",
    "claims_coordination_claim_operator_release",
    "claims_coordination_claim_release",
]
