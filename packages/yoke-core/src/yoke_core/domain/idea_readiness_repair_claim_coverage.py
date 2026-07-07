"""Claim-coverage auto-repair for refine-entry readiness checks."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.idea_readiness_check import _strip_sun_prefix
from yoke_core.domain.idea_readiness_repair import (
    CLASS_MIXED_STALE_COUNT,
    RepairOutcome,
    RepairedPath,
    _RECOVERABLE_CLAIM_CODES,
)
from yoke_core.domain.path_claims import PathClaimError
from yoke_core.domain.path_claims_amend import (
    AmendmentError,
    NarrowWouldOrphanCommittedWork,
    narrow,
    widen,
)
from yoke_core.domain.path_claims_events import emit_amended
from yoke_core.domain.path_claims_read import claim_projection, item_view
from yoke_core.domain.path_claims_resolve import (
    PathResolveError,
    resolve_paths_to_target_ids,
)
from yoke_core.domain.project_checkout_locations import checkout_for_project


REPAIR_ACTION_WIDEN = "widen"
REPAIR_ACTION_NARROW = "narrow"
REPAIR_ACTION_REFUSE = "refuse"
REPAIR_ACTION_MIXED = "widen_and_narrow"

_WIDEN_CODE = "FILE_BUDGET_NOT_IN_CLAIM"
_NARROW_CODE = "CLAIM_NOT_IN_FILE_BUDGET"
_FIELD_WRITTEN = ""
_EVENT_NAME = "IdeaReadinessClaimCoverageRepairApplied"
_WIDEN_REASON = "refine entry: auto-widen for FILE_BUDGET_NOT_IN_CLAIM"
_NARROW_REASON = "refine entry: auto-narrow for CLAIM_NOT_IN_FILE_BUDGET"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _classify_repair_action(
    codes: Set[str],
) -> Literal["widen", "narrow", "refuse"]:
    """Map recoverable claim-coverage codes to a repair action."""
    if not codes or (codes - _RECOVERABLE_CLAIM_CODES):
        return REPAIR_ACTION_REFUSE
    if codes == {_WIDEN_CODE}:
        return REPAIR_ACTION_WIDEN
    if codes == {_NARROW_CODE}:
        return REPAIR_ACTION_NARROW
    return REPAIR_ACTION_REFUSE


def _open_conn() -> Any:
    from yoke_core.domain.db_helpers import connect, resolve_db_path

    return connect(resolve_db_path())


def _find_single_exclusive_claim(
    conn: Any, item_id: int,
) -> Tuple[Optional[int], List[Dict[str, Any]]]:
    """Resolve the single non-terminal exclusive claim id for ``item_id``."""
    claims = item_view(conn, item_id, states=("planned", "active", "blocked"))
    exclusive = [c for c in claims if str(c.get("mode") or "") == "exclusive"]
    if not exclusive:
        return None, [{"reason": "no_exclusive_claim", "item_id": item_id}]
    if len(exclusive) > 1:
        return None, [{
            "reason": "multiple_exclusive_claims", "item_id": item_id,
            "claim_ids": [int(c["id"]) for c in exclusive],
        }]
    return int(exclusive[0]["id"]), []


def _paths_from_issues(issues: List[Dict[str, Any]], code: str) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for issue in issues:
        if str(issue.get("code") or "") != code:
            continue
        path = str((issue.get("context") or {}).get("path") or "")
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _scalar(conn, sql: str, params: tuple, key: str) -> Optional[str]:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    value = row[key] if hasattr(row, "keys") else row[0]
    return str(value) if value else None


def _project_for_item(conn, item_id: int) -> Optional[str]:
    p = _p(conn)
    return _scalar(
        conn,
        "SELECT p.slug AS project FROM items i "
        "LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE i.id = {p}",
        (item_id,),
        "project",
    )


def _repo_path_for_project(conn, project_id: str) -> Optional[str]:
    checkout = checkout_for_project(conn, project_id)
    return str(checkout) if checkout is not None else None


def _emit_repair_event(
    *, item_id: int, action: str, rerun_verdict: str,
    repaired: List[RepairedPath], refused: List[Dict[str, Any]],
) -> bool:
    """Emit ``IdeaReadinessClaimCoverageRepairApplied`` (best-effort)."""
    try:
        from yoke_core.domain.events import emit_event

        result = emit_event(
            _EVENT_NAME,
            event_kind="lifecycle", event_type="readiness_repair",
            source_type="backend", severity="INFO", outcome="completed",
            item_id=str(item_id),
            context={
                "field": _FIELD_WRITTEN, "action": action,
                "rerun_verdict": rerun_verdict,
                "repaired_paths": [asdict(p) for p in repaired],
                "refused_paths": refused,
            },
        )
        return bool(getattr(result, "wrote", False) or getattr(result, "event_id", ""))
    except Exception:
        return False


def _rerun_readiness(item_id: int) -> Tuple[str, List[Dict[str, Any]]]:
    from yoke_core.domain.idea_readiness_check import run_all_checks
    from yoke_core.domain.schema_common import _connect_raw, _resolve_db_path

    conn = _connect_raw(_resolve_db_path())
    try:
        issues = run_all_checks(conn, item_id)
    finally:
        conn.close()
    payload = [
        {"code": i.code, "message": i.message,
         "remediation": i.remediation, "context": i.context}
        for i in issues
    ]
    return ("pass" if not issues else "block", payload)


_AMEND_EXCS = (AmendmentError, PathClaimError, PathResolveError)


def _apply_widen(
    conn, *, claim_id: int, project: str, paths: List[str],
) -> Tuple[List[RepairedPath], List[Dict[str, Any]]]:
    try:
        target_ids = resolve_paths_to_target_ids(conn, project, paths)
        amendment_id = widen(
            conn, claim_id=claim_id, add_target_ids=target_ids,
            reason=_WIDEN_REASON,
        )
        emit_amended(
            conn=conn, claim=claim_projection(conn, claim_id),
            amendment_id=amendment_id, amendment_kind="widen",
            payload={"added": list(target_ids)},
            reason=_WIDEN_REASON, project=project,
        )
    except _AMEND_EXCS as exc:
        return [], [{"reason": "widen_failed", "paths": list(paths),
                     "error": str(exc)}]
    return [RepairedPath(path=p, recorded=0, actual=0) for p in paths], []


def _apply_narrow(
    conn, *, claim_id: int, project: str, drop_paths: List[str],
    repo_path: Optional[str],
) -> Tuple[List[RepairedPath], List[Dict[str, Any]]]:
    if not repo_path:
        return [], [{"reason": "narrow_boundary_checkout_missing",
                     "drop_paths": list(drop_paths)}]
    try:
        target_ids = resolve_paths_to_target_ids(conn, project, drop_paths)
        amendment_id = narrow(
            conn, claim_id=claim_id, drop_target_ids=target_ids,
            reason=_NARROW_REASON, repo_path=repo_path,
        )
        emit_amended(
            conn=conn, claim=claim_projection(conn, claim_id),
            amendment_id=amendment_id, amendment_kind="narrow",
            payload={"removed": list(target_ids)},
            reason=_NARROW_REASON, project=project,
        )
    except NarrowWouldOrphanCommittedWork as exc:
        return [], [{
            "reason": "narrow_boundary_risk",
            "offending_paths": list(exc.offending_paths),
            "error": str(exc),
        }]
    except _AMEND_EXCS as exc:
        return [], [{"reason": "narrow_failed",
                     "drop_paths": list(drop_paths), "error": str(exc)}]
    return (
        [RepairedPath(path=p, recorded=0, actual=0) for p in drop_paths], [],
    )


def attempt_claim_coverage_repair(
    *, item_id: int, issues: List[Dict[str, Any]],
) -> RepairOutcome:
    """Repair claim-coverage drift on the item's single exclusive claim.

    Routes widen / narrow / mixed amendment from the recoverable
    claim-coverage code set; refuses non-recoverable codes and ambiguous
    claim shapes with structured ``refused_paths``.
    """
    base = {"classification": CLASS_MIXED_STALE_COUNT, "item_id": item_id}
    codes: Set[str] = {str(i.get("code") or "") for i in issues}

    foreign = codes - _RECOVERABLE_CLAIM_CODES
    if foreign:
        return RepairOutcome(
            success=False, **base,
            refused_paths=[{"reason": "non_recoverable_codes_present",
                            "codes": sorted(foreign)}],
            error="non-recoverable codes mixed in; refuse by contract",
        )

    if {_WIDEN_CODE, _NARROW_CODE} <= codes:
        action = REPAIR_ACTION_MIXED
    else:
        action = _classify_repair_action(codes)
    if action == REPAIR_ACTION_REFUSE:
        return RepairOutcome(
            success=False, **base,
            refused_paths=[{"reason": "no_recoverable_codes",
                            "codes": sorted(codes)}],
            error="no recoverable claim-coverage codes to repair",
        )

    conn = _open_conn()
    try:
        claim_id, refused = _find_single_exclusive_claim(conn, item_id)
        if claim_id is None:
            return RepairOutcome(success=False, **base, refused_paths=refused,
                                 error=str(refused[0].get("reason")))
        project = _project_for_item(conn, item_id)
        if not project:
            return RepairOutcome(
                success=False, **base,
                refused_paths=[{"reason": "item_has_no_project",
                                "item_id": item_id}],
                error="item has no project; cannot resolve paths",
            )
        repo_path = _repo_path_for_project(conn, project)
        repaired: List[RepairedPath] = []
        apply_refused: List[Dict[str, Any]] = []
        if _WIDEN_CODE in codes:
            r, ar = _apply_widen(
                conn, claim_id=claim_id, project=project,
                paths=_paths_from_issues(issues, _WIDEN_CODE),
            )
            repaired += r
            apply_refused += ar
        if _NARROW_CODE in codes:
            r, ar = _apply_narrow(
                conn, claim_id=claim_id, project=project,
                drop_paths=_paths_from_issues(issues, _NARROW_CODE),
                repo_path=repo_path,
            )
            repaired += r
            apply_refused += ar
        if apply_refused and not repaired:
            return RepairOutcome(success=False, **base,
                                 refused_paths=apply_refused,
                                 error="repair refused before mutation")
    finally:
        conn.close()

    rerun_verdict, rerun_issues = _rerun_readiness(item_id)
    audit_emitted = _emit_repair_event(
        item_id=item_id, action=action, rerun_verdict=rerun_verdict,
        repaired=repaired, refused=apply_refused,
    )
    return RepairOutcome(
        success=(rerun_verdict == "pass"), **base,
        repaired_paths=repaired, field_written=_FIELD_WRITTEN,
        rerun_verdict=rerun_verdict, rerun_issues=rerun_issues,
        refused_paths=apply_refused, audit_emitted=audit_emitted,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=(
            "python3 -m yoke_core.domain.idea_readiness_repair_claim_coverage"
        ),
        description=(
            "Auto-repair claim-coverage readiness gaps via widen or narrow. "
            "Exits 0 only when the post-repair readiness verdict is pass."
        ),
    )
    parser.add_argument("--item", required=True, help="YOK-N or N")
    args = parser.parse_args(argv)
    try:
        item_id = int(_strip_sun_prefix(args.item))
    except ValueError:
        print(json.dumps({"success": False,
                          "error": f"invalid item: {args.item!r}"}))
        return 1
    verdict, issues = _rerun_readiness(item_id)
    if verdict == "pass":
        print(json.dumps({
            "success": True, "item_id": item_id, "rerun_verdict": "pass",
        }))
        return 0
    outcome = attempt_claim_coverage_repair(item_id=item_id, issues=issues)
    print(json.dumps(outcome.to_payload(), sort_keys=True))
    return 0 if outcome.success else 1


__all__ = [
    "REPAIR_ACTION_MIXED", "REPAIR_ACTION_NARROW", "REPAIR_ACTION_REFUSE",
    "REPAIR_ACTION_WIDEN", "attempt_claim_coverage_repair", "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
