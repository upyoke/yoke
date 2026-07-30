"""Legacy item-based pipeline entry: resolve an item ref to a fresh run.

The pipeline's primary argument is normally a ``run-*`` id; the legacy
shape passes an item ref instead. This module resolves that ref to the
internal ``items.id`` (``PREFIX-N`` via the project's
``public_item_prefix`` + ``items.project_sequence``; a bare number stays
an internal id), auto-creates a deployment run for the item's assigned
flow, and returns the run context. Adapter calls pass the bare internal
id so no re-resolution happens downstream; operator-facing messages echo
the caller's original ref.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import List, Optional

from yoke_core.domain.deploy_pipeline_reporting import _yoke_db
from yoke_core.domain.yok_n_parser import parse_item_id_or_none


@dataclass(frozen=True)
class LegacyItemRun:
    run_id: str
    project: str
    flow_id: str
    member_items: List[str]


def create_run_for_item_ref(
    primary_arg: str, *, sd: Optional[str] = None
) -> Optional[LegacyItemRun]:
    """Auto-create a deployment run for an item ref; None on failure.

    Failure paths print their own operator-facing error to stderr.
    """
    resolved_item = parse_item_id_or_none(primary_arg, allow_bare_internal=True)
    if resolved_item is None:
        print(f"Error: cannot parse item ref '{primary_arg}'", file=sys.stderr)
        return None
    item_num = str(resolved_item)
    print(
        "Warning: Legacy item-based pipeline invocation. "
        "Auto-creating a deployment run.",
        file=sys.stderr,
    )

    flow_id = _yoke_db("items", "get", item_num, "deployment_flow", sd=sd)
    project = _yoke_db("items", "get", item_num, "project", sd=sd)

    if not flow_id:
        print(
            f"Error: {primary_arg} has no deployment_flow assigned",
            file=sys.stderr,
        )
        return None
    if not project:
        print(f"Error: {primary_arg} has no project assigned", file=sys.stderr)
        return None

    run_id = _yoke_db(
        "runs", "create-run", project, flow_id, "--created-by", "system", sd=sd
    )
    if not run_id:
        print(
            f"Error: failed to auto-create deployment run for {primary_arg}",
            file=sys.stderr,
        )
        return None

    _yoke_db("runs", "add-item", run_id, item_num, sd=sd)
    print(f"Auto-created run {run_id} for {primary_arg}")
    return LegacyItemRun(
        run_id=run_id,
        project=project,
        flow_id=flow_id,
        member_items=[item_num],
    )


__all__ = ["LegacyItemRun", "create_run_for_item_ref"]
