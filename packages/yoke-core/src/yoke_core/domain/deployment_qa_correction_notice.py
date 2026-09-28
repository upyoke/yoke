"""Wake the owner when a corrected deployment QA case becomes executable."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain.deployment_run_driver_notice import (
    push_member_notice,
    push_run_scoped_notice,
)
from yoke_core.domain.project_identity import render_item_ref, resolve_project


def notify_correction(
    conn: Any,
    *,
    result: Mapping[str, Any],
    replacements: Sequence[Mapping[str, int]],
) -> dict[str, str]:
    run_id = str(result["deployment_run_id"])
    stage = str(result["deployment_stage"])
    member = result.get("deployment_member_item_id")
    ids = tuple(sorted(int(row["replacement_requirement_id"]) for row in replacements))
    run = conn.execute(
        "SELECT project_id FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    if run is None:
        raise ValueError(f"deployment run {run_id} disappeared after correction")
    project_id = int(run["project_id"])
    if member is not None:
        item = conn.execute("SELECT project_id FROM items WHERE id=%s", (int(member),)).fetchone()
        if item is None:
            raise ValueError(f"deployment member {member} disappeared after correction")
        project_id = int(item["project_id"])
    project = resolve_project(conn, project_id)
    scope = f" --member {render_item_ref(conn, int(member))}" if member is not None else ""
    command = (
        f"yoke watch qa-plan -- --deployment-run-id {run_id} --stage {stage}"
        f"{scope} --project {project.slug}"
    )
    body = (
        f"Corrected QA requirement(s) {', '.join(map(str, ids))} are ready "
        f"for deployment run {run_id} stage {stage!r}. Run `{command}` on "
        "the pinned deployed target. The failed attempt remains history; "
        f"inspect `yoke deployment-runs get {run_id}` for any sibling blocker."
    )
    key = f"deployment-qa-correction:{run_id}:{stage}:{member or 'run'}:{','.join(map(str, ids))}"
    if member is None:
        delivery = push_run_scoped_notice(
            conn, project_id=project_id, body_for_route=lambda route: body,
            idempotency_key=key,
        )
    else:
        delivery = push_member_notice(
            conn, item_id=int(member), project_id=project_id,
            body_for_route=lambda route: body, idempotency_key=key,
        )
    conn.commit()
    return {
        "delivery": delivery or "unaddressed",
        "recovery": "" if delivery else f"No holder or steering seat; run `{command}` and inspect run {run_id}.",
    }
