"""Engine-owned worktree preparation for Dash and Blitz execution."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import partial
import json
import os
import sys
from typing import Iterator, List, Optional

from yoke_core.domain.worktree_preflight import run_preflight
from yoke_core.tools._source_pythonpath import SOURCE_RUN_RECIPE


@contextmanager
def _session_identity(session_id: str) -> Iterator[None]:
    previous = os.environ.get("YOKE_SESSION_ID")
    if session_id:
        os.environ["YOKE_SESSION_ID"] = session_id
    try:
        yield
    finally:
        if session_id:
            if previous is None:
                os.environ.pop("YOKE_SESSION_ID", None)
            else:
                os.environ["YOKE_SESSION_ID"] = previous


def _prepare_dash_path_claim(
    *,
    item_id: int,
    touch_paths: tuple[str, ...],
    integration_target: str,
) -> Optional[str]:
    """Ensure the selected-Dash path claim reflects the live survey.

    Routes both the work-claim-holder read and the register/widen
    through the transport-aware dispatcher so an https-connected session
    relays them to the control plane instead of opening a local Postgres
    connection. The holder read (``claims.work.holder_get``) preserves
    the "no live item work claim" refusal; the register-or-widen decision
    stays server-side behind ``claims.path.survey_ensure`` (the register
    function alone cannot express the widen case). Returns an error
    string to block preparation, or ``None`` on success / no-op.
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    target = TargetRef(kind="item", item_id=int(item_id))
    holder = call_dispatcher(
        function_id="claims.work.holder_get",
        target=target,
    )
    if not holder.success:
        err = holder.error
        return (
            f"{err.code}: {err.message}"
            if err is not None
            else "work-claim holder lookup failed"
        )
    holder_row = (holder.result or {}).get("holder")
    if not holder_row or not holder_row.get("session_id"):
        return "Dash path-claim preparation has no live item work claim"

    ensured = call_dispatcher(
        function_id="claims.path.survey_ensure",
        target=target,
        payload={
            "touch_paths": list(touch_paths),
            "integration_target": integration_target,
        },
    )
    if not ensured.success:
        err = ensured.error
        return (
            err.message if err is not None
            else "Dash path-claim preparation failed"
        )
    return None


def run(args: List[str]) -> int:
    """Validate the recorded survey, then prepare the ordinary item lane."""
    parser = argparse.ArgumentParser(
        prog="yoke direct-workflow worktree prepare",
    )
    parser.add_argument("item")
    parser.add_argument("--workflow", choices=("dash", "blitz"), required=True)
    parser.add_argument("--project")
    parser.add_argument(
        "--session-id",
        default=os.environ.get("YOKE_SESSION_ID", ""),
    )
    parsed = parser.parse_args(args)

    # Route control-plane reads through the transport-aware dispatcher so an
    # https-connected session relays them to the server instead of opening a
    # local Postgres connection (which the https transport refuses). Item-ref
    # resolution happens server-side from the ``item_ref`` target; the
    # recorded-survey read and conflict re-check run server-side too.
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    detail = call_dispatcher(
        function_id="items.detail.get",
        target=TargetRef(
            kind="item",
            item_ref=str(parsed.item),
            project_id=parsed.project,
        ),
    )
    if not detail.success:
        message = (
            detail.error.message if detail.error is not None
            else "item ref resolution failed"
        )
        parser.error(f"could not resolve item {parsed.item!r}: {message}")
    item = (detail.result or {}).get("item") or {}
    item_id = int(item["id"])
    workflow_id = str((item.get("workflow") or {}).get("id") or "missing")
    if workflow_id != parsed.workflow:
        parser.error(
            f"item uses workflow {workflow_id!r}, not {parsed.workflow!r}"
        )

    status = call_dispatcher(
        function_id="direct_workflow.conflict_survey.status",
        target=TargetRef(kind="item", item_id=item_id),
    )
    if not status.success:
        message = (
            status.error.message if status.error is not None
            else "conflict survey status failed"
        )
        parser.error(f"conflict survey status unavailable: {message}")
    survey = status.result or {}
    if not survey.get("found"):
        print(json.dumps({
            "ok": False,
            "block_kind": "conflict-survey-missing",
            "narrative": (
                "Record the inferred touch set before worktree preparation."
            ),
            "item_id": item_id,
        }))
        return 1
    if not survey.get("clear"):
        print(json.dumps({
            "ok": False,
            "block_kind": "conflict-survey-blocked",
            "narrative": (
                "Registered coordination wins over claim-less work."
            ),
            "item_id": item_id,
            "blockers": survey.get("blockers") or [],
        }))
        return 1
    touch_paths = tuple(survey.get("touch_paths") or ())
    integration_target = str(survey.get("integration_target") or "main")

    with _session_identity(parsed.session_id):
        claim_preparer = None
        if parsed.workflow == "dash":
            claim_preparer = partial(
                _prepare_dash_path_claim,
                item_id=item_id,
                touch_paths=touch_paths,
                integration_target=integration_target,
            )
        outcome = run_preflight(
            item_id=item_id,
            project=parsed.project,
            session_id=parsed.session_id,
            actual_cwd=os.getcwd(),
            prepare_path_claims=claim_preparer,
        )
    envelope = outcome.to_envelope()
    if outcome.ok:
        envelope["source_dev_recipe"] = SOURCE_RUN_RECIPE
    print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0 if outcome.ok else 1


def main(argv: Optional[List[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
