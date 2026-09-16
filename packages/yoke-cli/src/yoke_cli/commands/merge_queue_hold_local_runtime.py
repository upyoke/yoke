"""Machine-local runtime for holding one merge-queue candidate.

Holding a live candidate is an operator act: policy requires the operator's
bound GitHub authorization rather than the installation the landing observer
runs as, so the mutation has to happen where that authorization exists. This
runtime binds it, keeps the operator-selected control plane, and calls the
same ``hold_landing`` the registered function calls.

Authority stays on the control plane. Ownership is the registered work-claim
holder read, and project authorization plus the resolved pull request come
from the registered readiness read; neither asks the serving build for this
runtime's own vocabulary, so a server older than this change answers both
exactly as a current one does.

The registered hold that records the outcome durably is itself a mutation
against a live pull request, not an audit write, so it can land or re-arm
between this runtime's proof and its own attempt. Its outcome is therefore
read, and a further authoritative readiness decides the verdict — pinned to
the same project, pull request, and target the first read resolved, because
a readback about a different candidate proves nothing about this one.

A hold whose result cannot be confirmed is reported unverified with its
local actions retained, never as held: the candidate may be live, and the
caller must not push against it.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import Any, Dict, List, Optional

from yoke_cli.commands.merge_item_local_runtime import (
    LocalMergeAuthorityError,
    machine_github_user_authority,
    same_universe_control_plane_authority,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef

HOLD_USAGE = "yoke github merge-queue hold ITEM [--project P] [--json]"

#: Ownership is the item's work claim, read through the registered holder
#: projection. A hold moves a live landing, so a session that does not hold
#: the item is refused rather than allowed to act on another lane's behalf.
_CLAIM_HOLDER_FUNCTION = "claims.work.holder_get"
#: Project authorization, the resolved pull request, and the authoritative
#: queue readback all come from this one registered read.
_READINESS_FUNCTION = "github.merge_queue.readiness"
#: Records the outcome durably. Called only once a readback already showed
#: the candidate clear, so it never doubles as an authorization probe — but
#: it mutates a live pull request, so its result is read back like any
#: other mutation.
_HOLD_FUNCTION = "github.merge_queue.hold"


class HoldRefused(RuntimeError):
    """The hold cannot proceed, with the reason the caller should read."""


def _call(function_id: str, item: str, project: Optional[str]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    response = call_dispatcher(
        function_id=function_id,
        target=item_target(item, project),
        payload=payload,
        actor=build_actor(),
    )
    if not response.success:
        message = response.error.message if response.error else "request failed"
        raise HoldRefused(f"{function_id} refused: {message}")
    return dict(response.result or {})


def item_target(item: str, project: Optional[str]) -> TargetRef:
    return TargetRef(kind="item", public_ref=item, project=project or None)


def _require_claim(item: str, project: Optional[str]) -> None:
    """Refuse unless this session holds the item's work claim."""
    holder = _call(_CLAIM_HOLDER_FUNCTION, item, project).get("holder")
    session = build_actor().session_id or ""
    if not isinstance(holder, dict) or not holder.get("session_id"):
        raise HoldRefused(
            f"{item} has no live work claim, so this session has no authority "
            "to move its landing; acquire the item's work claim first"
        )
    if str(holder.get("session_id")) != session:
        raise HoldRefused(
            f"{item} is held by session {holder.get('session_id')!r}, not this "
            "one; a hold moves a live landing, so only the holder may run it"
        )


def _readiness(item: str, project: Optional[str]) -> Dict[str, Any]:
    """The authoritative readback, and the project authorization with it."""
    result = _call(_READINESS_FUNCTION, item, project)
    if not str(result.get("pr_number") or ""):
        raise HoldRefused(
            f"{item} has no recorded pull request to hold; "
            f"{result.get('narrative') or 'nothing was read back'}"
        )
    return result


def _queue_clear(readiness: Dict[str, Any]) -> bool:
    """Whether the readback itself shows nothing left to hold."""
    return (
        str(readiness.get("queue_entry_state") or "") == "absent"
        and str(readiness.get("merge_when_ready") or "") == "cleared"
    )


def _identity_drift(first: Dict[str, Any], last: Dict[str, Any]) -> str:
    """Name any field that makes the two reads describe different candidates."""
    for field in ("project", "pr_number", "target"):
        if str(first.get(field) or "") != str(last.get(field) or ""):
            return f"{field} was {first.get(field)!r} and is now {last.get(field)!r}"
    return ""


def _hold_locally(readiness: Dict[str, Any]) -> Any:
    """Run the existing hold against GitHub under this process's authority."""
    hold_mod = importlib.import_module("yoke_core.domain.merge_queue_hold")
    prepare = importlib.import_module("yoke_core.engines.merge_worktree_prepare")
    # No head branch: a hold addresses the pull request by number, and the
    # registered readiness handler builds its own context the same way.
    ctx = prepare.MergeContext(
        args=prepare.MergeArgs(
            branch="",
            target=str(readiness.get("target") or ""),
        ),
        project=str(readiness.get("project") or ""),
    )
    return hold_mod.hold_landing(
        ctx,
        pr_number=str(readiness.get("pr_number") or ""),
        target=str(readiness.get("target") or ""),
    )


def run(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke github merge-queue hold")
    parser.add_argument("item")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    parsed = parser.parse_args(argv)

    with machine_github_user_authority(), same_universe_control_plane_authority():
        _require_claim(parsed.item, parsed.project)
        before = _readiness(parsed.item, parsed.project)
        if before.get("merged"):
            return _emit(parsed, "already_landed", before, held=False, actions=())
        if _queue_clear(before):
            return _emit(parsed, "already_clear", before, held=True, actions=())

        local = _hold_locally(before)
        actions = tuple(local.actions)

        # The candidate's real state after the local mutations, read from the
        # control plane rather than inferred from what they returned.
        try:
            after = _readiness(parsed.item, parsed.project)
        except HoldRefused as exc:
            return _emit(
                parsed,
                "unverified",
                before,
                held=False,
                actions=actions,
                refusal=(
                    f"local actions ran but the confirming readback failed "
                    f"({exc}); treat the candidate as live and do not push"
                ),
            )
        if after.get("merged"):
            return _emit(
                parsed, "landed_during_hold", after, held=False, actions=actions
            )
        if not _queue_clear(after):
            return _emit(
                parsed,
                "not_held",
                after,
                held=False,
                actions=actions,
                refusal=(
                    "the readback still shows the candidate live; it is not "
                    "held, so do not push a correction against it"
                ),
            )

        # Clear is proven, so this records the outcome durably — but it is a
        # mutation against a live pull request and can be overtaken, so the
        # verdict comes from a final authoritative read, not from here.
        try:
            recorded = _call(_HOLD_FUNCTION, parsed.item, parsed.project)
            confirmation = str(recorded.get("outcome") or "")
        except HoldRefused as exc:
            confirmation = f"not recorded ({exc})"
        try:
            final = _readiness(parsed.item, parsed.project)
        except HoldRefused as exc:
            return _emit(
                parsed,
                "unverified",
                after,
                held=False,
                actions=actions,
                confirmation=confirmation,
                refusal=(
                    f"the record was attempted but the final readback failed "
                    f"({exc}); treat the candidate as live and do not push"
                ),
            )
        drift = _identity_drift(before, final)
        if drift:
            return _emit(
                parsed,
                "unverified",
                final,
                held=False,
                actions=actions,
                confirmation=confirmation,
                refusal=(
                    f"the final readback describes a different candidate "
                    f"({drift}); treat this one as live and do not push"
                ),
            )
        if final.get("merged"):
            return _emit(
                parsed,
                "landed_during_hold",
                final,
                held=False,
                actions=actions,
                confirmation=confirmation,
            )
        if not _queue_clear(final):
            return _emit(
                parsed,
                "not_held",
                final,
                held=False,
                actions=actions,
                confirmation=confirmation,
                refusal=(
                    "the candidate is live again after the record; it is not "
                    "held, so do not push a correction against it"
                ),
            )
        return _emit(
            parsed,
            "held",
            final,
            held=True,
            actions=actions,
            confirmation=confirmation,
        )


def _emit(
    parsed: argparse.Namespace,
    outcome: str,
    readiness: Dict[str, Any],
    *,
    held: bool,
    actions: tuple,
    refusal: str = "",
    confirmation: str = "",
) -> int:
    result = {
        "outcome": outcome,
        "held": held,
        "public_ref": parsed.item,
        "pr_number": readiness.get("pr_number"),
        "target": readiness.get("target"),
        "actions": list(actions),
        "readback": readiness.get("narrative"),
        "durable_confirmation": confirmation,
        "refusal": refusal,
    }
    if parsed.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"hold {outcome}: {parsed.item} pull request {result['pr_number']}")
        for action in actions:
            print(f"  {action}")
        if readiness.get("narrative"):
            print(f"  readback: {readiness['narrative']}")
        if confirmation:
            print(f"  durable confirmation: {confirmation}")
        if refusal:
            print(f"  {refusal}", file=sys.stderr)
    return 0 if held else 1


def main(argv: Optional[List[str]] = None) -> int:
    try:
        return run(list(sys.argv[1:] if argv is None else argv))
    except (HoldRefused, LocalMergeAuthorityError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


__all__ = ["HOLD_USAGE", "HoldRefused", "item_target", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
