"""Companion read handlers: path_claims conflicts, doctor.run.run, capability.has.

Split from ``handlers/reads`` so each file stays under the file-line cap.
Function ids registered from this module carry ``claim_required_kind=None``;
none requires an active claim.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


# ---------------------------------------------------------------------------
# path_claims.conflicts.list.run
# ---------------------------------------------------------------------------


class PathClaimsConflictsRequest(BaseModel):
    integration_target: Optional[str] = None


class PathClaimsConflictsResponse(BaseModel):
    conflicts: List[Dict[str, Any]]


def handle_path_claims_conflicts(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.path_claims_read import cross_claim_conflicts

    integration_target = (request.payload or {}).get("integration_target")
    conn = connect()
    try:
        conflicts = cross_claim_conflicts(
            conn,
            integration_target=(
                str(integration_target) if integration_target else None
            ),
        )
    finally:
        conn.close()
    item_id = request.target.item_id
    if item_id is not None:
        filtered = []
        for c in conflicts:
            try:
                self_item = c.get("self", {}).get("item_id")
                other_item = c.get("other", {}).get("item_id")
                if (self_item is not None and int(self_item) == int(item_id)) or (
                    other_item is not None and int(other_item) == int(item_id)
                ):
                    filtered.append(c)
            except (TypeError, ValueError):
                continue
        conflicts = filtered
    return HandlerOutcome(
        result_payload={"conflicts": conflicts},
        primary_success=True,
    )


# ---------------------------------------------------------------------------
# doctor.run.run
# ---------------------------------------------------------------------------
#
# Machine-callable Doctor surface. The request mirrors the human CLI's
# DoctorArgs: project / db_path / fix / only / quick / full. Callers must
# pick exactly one scope (quick | full | only) — the explicit-scope rule
# is enforced server-side so JSON callers cannot
# silently burn quota by omitting it. Unknown HC slugs in ``only`` return
# a structured ``invalid_check`` error rather than a successful empty
# result.


class DoctorRunRequest(BaseModel):
    only: Optional[str] = None
    quick: bool = False
    full: bool = False
    fix: bool = False
    project: str = "yoke"
    db_path: Optional[str] = None


class DoctorRunResponse(BaseModel):
    results: List[Dict[str, Any]]
    scope: str
    project: str
    fail_count: int
    warn_count: int
    pass_count: int


def handle_doctor_run(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.handlers.doctor_run_scope import (
        doctor_scope_label,
        filter_source_tree_checks,
        validate_only_slugs,
    )
    from yoke_core.engines.doctor_registry import HEALTH_CHECKS, _should_run_hc
    from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector

    payload = request.payload or {}
    only_raw = payload.get("only")
    quick = bool(payload.get("quick", False))
    full = bool(payload.get("full", False))
    cursor_after_raw = payload.get("cursor_after")
    max_checks_raw = payload.get("max_checks")

    # Exactly one of quick / full / only must be supplied — defends against
    # JSON callers silently running the full GitHub-dependent suite.
    scope_flags = [bool(quick), bool(full), bool(only_raw)]
    if sum(scope_flags) != 1:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="scope_required",
                message=(
                    "doctor.run.run requires exactly one scope: "
                    "quick=true, full=true, or only=<slug,slug...>. "
                    "The explicit-scope rule prevents silent gh-quota burn."
                ),
                jsonpath="$.payload",
            ),
        )

    if only_raw is not None and not isinstance(only_raw, str):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="only must be a comma-separated string of slugs",
                jsonpath="$.payload.only",
            ),
        )

    if only_raw:
        unknown = validate_only_slugs(only_raw)
        if unknown:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="invalid_check",
                    message=(
                        "unknown HC slug(s): " + ", ".join(unknown)
                        + ". Use only registered slugs (list via "
                        "`python3 -m yoke_core.engines.doctor --list-checks`)."
                    ),
                    jsonpath="$.payload.only",
                ),
            )

    if cursor_after_raw is not None and not isinstance(cursor_after_raw, str):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="cursor_after must be a health-check slug",
                jsonpath="$.payload.cursor_after",
            ),
        )
    max_checks = None
    if max_checks_raw is not None:
        try:
            max_checks = int(max_checks_raw)
        except (TypeError, ValueError):
            max_checks = 0
        if max_checks <= 0:
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="payload_invalid",
                    message="max_checks must be a positive integer",
                    jsonpath="$.payload.max_checks",
                ),
            )

    db_path = payload.get("db_path")
    args = DoctorArgs(
        only=only_raw,
        quick=quick,
        project=str(payload.get("project") or "yoke"),
        fix=bool(payload.get("fix", False)),
        db_path=str(db_path) if db_path else None,
    )
    rec = RecordCollector()
    conn = connect(path=args.db_path)
    skip_source_tree_checks = bool(payload.get("skip_source_tree_checks", False))
    project_safe_quick = (
        skip_source_tree_checks
        and args.quick
        and not args.only
        and not args.fix
        and args.project != "yoke"
    )
    selected = filter_source_tree_checks(
        [hc for hc in HEALTH_CHECKS if _should_run_hc(hc.slug, args)],
        skip=skip_source_tree_checks,
        project_safe_quick=project_safe_quick,
    )
    start_index = 0
    cursor_after = (cursor_after_raw or "").strip()
    if cursor_after:
        selected_slugs = [hc.slug for hc in selected]
        try:
            start_index = selected_slugs.index(cursor_after) + 1
        except ValueError:
            conn.close()
            return HandlerOutcome(
                primary_success=False,
                error=FunctionError(
                    code="invalid_cursor",
                    message=(
                        "cursor_after does not match this doctor scope: "
                        f"{cursor_after}"
                    ),
                    jsonpath="$.payload.cursor_after",
                ),
            )
    ran_count = 0
    last_cursor = cursor_after or None
    try:
        for hc in selected[start_index:]:
            if max_checks is not None and ran_count >= max_checks:
                break
            try:
                hc.fn(conn, args, rec)
            except Exception as exc:  # pragma: no cover - defensive
                rec.record(
                    f"HC-{hc.slug}", hc.name, "FAIL",
                    f"Internal error: {exc}",
                )
            ran_count += 1
            last_cursor = hc.slug
    finally:
        conn.close()
    done = start_index + ran_count >= len(selected)
    results = [
        {
            "hc": r.check_id,
            "name": r.check_name,
            "severity": r.result,
            "detail": r.detail,
        }
        for r in rec.results
    ]
    return HandlerOutcome(
        result_payload={
            "results": results,
            "scope": doctor_scope_label(args),
            "project": args.project,
            "fail_count": rec.fail_count,
            "warn_count": rec.warn_count,
            "pass_count": rec.pass_count,
            "done": done,
            "cursor": last_cursor,
        },
        primary_success=True,
    )


# ---------------------------------------------------------------------------
# projects.capability.has.run
# ---------------------------------------------------------------------------


class ProjectsCapabilityHasRequest(BaseModel):
    project: str
    cap_type: str


class ProjectsCapabilityHasResponse(BaseModel):
    project: str
    cap_type: str
    has: bool


def handle_projects_capability_has(request: FunctionCallRequest) -> HandlerOutcome:
    payload = request.payload or {}
    project = payload.get("project")
    cap_type = payload.get("cap_type")
    if not project or not isinstance(project, str):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="project is required",
                jsonpath="$.payload.project",
            ),
        )
    if not cap_type or not isinstance(cap_type, str):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="payload_invalid",
                message="cap_type is required",
                jsonpath="$.payload.cap_type",
            ),
        )
    from yoke_core.domain.projects_crud import cmd_has_capability

    has = bool(cmd_has_capability(project, cap_type))
    return HandlerOutcome(
        result_payload={
            "project": project,
            "cap_type": cap_type,
            "has": has,
        },
        primary_success=True,
    )


__all__ = [
    "PathClaimsConflictsRequest", "PathClaimsConflictsResponse",
    "handle_path_claims_conflicts",
    "DoctorRunRequest", "DoctorRunResponse", "handle_doctor_run",
    "ProjectsCapabilityHasRequest", "ProjectsCapabilityHasResponse",
    "handle_projects_capability_has",
]
