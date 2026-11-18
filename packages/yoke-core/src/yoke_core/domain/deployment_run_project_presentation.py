"""Project-scoped projections of shared deployment records."""

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.deployment_run_bound_sources import (
    declared_bindings,
    parse_bound_sources,
)
from yoke_core.domain.json_helper import loads_text


def project_visible(project_id: object, visible: set[int] | None) -> bool:
    if visible is None:
        return True
    text = str(project_id)
    return text.isascii() and text.isdecimal() and int(text) in visible


def visible_bound_sources(
    raw: Any, stages: Any, visible: set[int] | None, *, owner_id: Any
) -> dict:
    sources = parse_bound_sources(raw)
    if visible is None:
        return sources
    projects = [
        dict(entry)
        for entry in sources["projects"] or ()
        if isinstance(entry, Mapping)
        and project_visible(entry.get("project_id"), visible)
    ]
    if not project_visible(owner_id, visible):
        # A hosted promotion receipt also records the owning product's SHA.
        from yoke_core.domain.hosted_promotion_receipt import PROMOTION_RECEIPTS_KEY

        for entry in projects:
            entry.pop(PROMOTION_RECEIPTS_KEY, None)
    project_refs = {entry.get("project") for entry in projects} - {None}
    try:
        bindings = declared_bindings(
            loads_text(stages) if isinstance(stages, str) else stages
        )
    except (TypeError, ValueError):
        bindings = {}
    # Input names are attributed by the flow binding. Commit values can be
    # shared across projects and cannot establish which project owns an input.
    return {
        "schema": sources["schema"],
        "projects": projects,
        "inputs": {
            name: value
            for name, value in (sources["inputs"] or {}).items()
            if bindings.get(name, {}).get("project") in project_refs
        },
    }


def visible_carried_work(
    payload: dict, owner_id: Any, visible: set[int] | None
) -> dict:
    if visible is None:
        return payload
    bound_projects = [
        entry
        for entry in payload.get("bound_projects") or []
        if project_visible(entry.get("project_id"), visible)
    ]
    own = (
        payload
        if project_visible(owner_id, visible)
        else {
            "schema": payload.get("schema"),
            "items": [],
            "commits": [],
        }
    )
    return {**own, "bound_projects": bound_projects}


def scope_run_fields(row: dict, visible: set[int] | None) -> None:
    if visible is None:
        return
    # This raw execution snapshot may contain cross-project plan/member data.
    # Member QA on cards is supplied by the authorized member projection.
    for name in ("requirement_snapshot", "composition_resolution"):
        if name in row:
            row[name] = ""
    if not project_visible(row.get("project_id"), visible):
        for name in (
            "project",
            "project_id",
            "release_lineage",
        ):
            if name in row:
                row[name] = ""
