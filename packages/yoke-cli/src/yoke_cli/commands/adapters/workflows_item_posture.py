"""``yoke workflows item-posture amend`` — change a filed posture selection.

Posture is chosen when an item is filed.  This adapter is how an item that was
filed without a selection — or with the wrong one — gets a different one
without being cancelled and re-filed.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.dash_verification_plan import (
    DashVerificationPlanError,
    resolve_dash_verification_plan,
)


# The one-line recipe every surface that teaches posture selection points at.
WORKFLOWS_ITEM_POSTURE_AMEND_RECIPE = (
    "yoke workflows item-posture amend PREFIX-N --verification-plan "
    "ID_OR_SLUG --reason TEXT"
)
WORKFLOWS_ITEM_POSTURE_AMEND_HINT = (
    "Posture selected at filing can be changed later without re-filing: "
    f"{WORKFLOWS_ITEM_POSTURE_AMEND_RECIPE} "
    "(--help for the per-key decision tree)."
)
WORKFLOWS_ITEM_POSTURE_AMEND_USAGE = (
    "yoke workflows item-posture amend ITEM --reason TEXT "
    "(--verification-plan ID_OR_SLUG | --verification-method ID | "
    "--key KEY (--value JSON | --clear)) "
    "[--project P] [--session-id S] [--json]"
)

WORKFLOWS_ITEM_POSTURE_AMEND_HELP = """
Which form to use
  Verification, the common case — the same two flags the filing surface
  takes, so a plan slug resolves here exactly as it does at create:

      yoke workflows item-posture amend PREFIX-N \\
        --verification-plan self-host-server-clean-room \\
        --reason "mission scheduled onto this item"
      yoke workflows item-posture amend PREFIX-N \\
        --verification-method implementation_review \\
        --reason "review-only close"

  Any other key, by name and JSON value:

      yoke workflows item-posture amend PREFIX-N --key path_claims \\
        --value true --reason "coordinating a shared path"
      yoke workflows item-posture amend PREFIX-N --key deployment \\
        --clear --reason "delivery moved to the batch run"

What it refuses, and why
  * A key the item's pinned workflow does not allow. The refusal names the
    allowlist that definition actually carries.
  * A key the vocabulary knows but no amendment guard declares. Amending it
    could strand records nothing checks, so it refuses by name instead.
  * An item at a terminal stage. Every posture gate has already run there.
  * Replacing a verification selection whose QA requirement already carries a
    recorded run — that evidence would be orphaned. Finish under the current
    selection, or waive the recorded requirement first.
  * Clearing path-claims while its claims are still registered, or clearing an
    approval selection while an owner decision is open on the done transition.

What it does besides the write
  Replacing a verification selection retires what the previous one left
  behind: unexecuted requirement snapshots are waived (never deleted, so the
  history stays readable) and a superseded plan attachment is removed. A new
  plan selection is attached at the review transition in the same
  transaction, so `yoke qa plan materialize` works immediately afterwards.

Reading the result
  `changed=false` means the stored selection already matched — the call is
  idempotent and writes nothing. Otherwise `before` / `after` carry the whole
  posture, and `waived_requirement_ids` / `detached_plan_ids` name everything
  the replacement retired.
"""


def workflows_item_posture_amend(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows item-posture amend",
        description=WORKFLOWS_ITEM_POSTURE_AMEND_USAGE,
        epilog=WORKFLOWS_ITEM_POSTURE_AMEND_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("--project", default=None)
    parser.add_argument(
        "--reason",
        required=True,
        help="Why the filed selection is changing. Recorded on the event.",
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--verification-plan",
        metavar="ID_OR_SLUG",
        help="Select plan verification; shorthand for --key verification.",
    )
    selection.add_argument(
        "--verification-method",
        help="Select ad-hoc verification; shorthand for --key verification.",
    )
    selection.add_argument(
        "--key",
        help="Posture key to amend, as the pinned workflow allowlist names it.",
    )
    value_group = parser.add_mutually_exclusive_group()
    value_group.add_argument(
        "--value",
        default=None,
        help="JSON value for --key (a boolean knob takes `true`).",
    )
    value_group.add_argument(
        "--clear",
        action="store_true",
        help="Remove --key from the stored posture.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, WORKFLOWS_ITEM_POSTURE_AMEND_USAGE
    )
    if parsed is None:
        return 2
    project = client_project_context(parsed.project)
    payload: Dict[str, Any] = {"reason": parsed.reason, "clear": False}
    if parsed.verification_plan is not None:
        try:
            plan_id = resolve_dash_verification_plan(
                parsed.verification_plan,
                project=project,
                session_id=parsed.session_id,
            )
        except DashVerificationPlanError as exc:
            return usage_error(str(exc))
        payload["key"] = "verification"
        payload["value"] = {"kind": "plan", "plan_id": plan_id}
    elif parsed.verification_method is not None:
        payload["key"] = "verification"
        payload["value"] = {
            "kind": "ad_hoc",
            "method_id": parsed.verification_method,
        }
    else:
        if parsed.value is None and not parsed.clear:
            return usage_error("--key requires either --value JSON or --clear")
        payload["key"] = parsed.key
        payload["clear"] = bool(parsed.clear)
        if not parsed.clear:
            try:
                payload["value"] = json.loads(parsed.value)
            except json.JSONDecodeError as exc:
                return usage_error(f"--value is not valid JSON: {exc}")

    def _human(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        print(
            "item-posture-amend|"
            + "|".join(
                str(result.get(field) or "")
                for field in ("item_id", "key", "changed")
            )
            + "|waived="
            + ",".join(str(value) for value in result.get(
                "waived_requirement_ids"
            ) or [])
            + "|detached="
            + ",".join(str(value) for value in result.get(
                "detached_plan_ids"
            ) or []),
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="workflows.item_posture.amend",
        target=item_target("item", parsed.item, project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human,
    )


USAGE_BY_FUNCTION_ID = {
    "workflows.item_posture.amend": WORKFLOWS_ITEM_POSTURE_AMEND_USAGE,
}


__all__ = [
    "USAGE_BY_FUNCTION_ID",
    "WORKFLOWS_ITEM_POSTURE_AMEND_HELP",
    "WORKFLOWS_ITEM_POSTURE_AMEND_HINT",
    "WORKFLOWS_ITEM_POSTURE_AMEND_RECIPE",
    "WORKFLOWS_ITEM_POSTURE_AMEND_USAGE",
    "workflows_item_posture_amend",
]
