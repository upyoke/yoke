"""Honor caller-checkout project-local slugs on https ``doctor.run --only``.

Relayed ``doctor.run.run`` validates ``only=`` against the server roster.
Project-local checks live in the caller's ``.yoke/doctor/`` folder and are
executed on the client anyway, so undeployed checkout-declared slugs must
be stripped from the relayed payload and run locally.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from yoke_core.domain.control_plane_transport import local_connection_or_none
from yoke_core.domain.db_helpers import connect
from yoke_core.engines.doctor_applicability import RUNTIME_LOCAL
from yoke_core.engines import doctor_progress
from yoke_core.engines.doctor_check_execution import execute_check_isolated
from yoke_core.engines.doctor_https_compose import (
    UnavailableControlPlane,
    checkout_root_for_project,
    note_missing_control_plane,
    recount,
)
from yoke_core.engines.doctor_project_checks import discover_project_checks
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines.doctor_roster import Roster, record_discovery_failures
from yoke_core.engines.doctor_source_root import bound_source_root


#: Same alias map the server-side ``validate_only_slugs`` helper accepts.
_ONLY_ALIASES = {"confabulation": "path-confabulation"}


def caller_project_local_slugs(project: str) -> set[str]:
    """Slugs declared under the caller's mapped checkout ``.yoke/doctor/``."""
    root = checkout_root_for_project(project)
    if root is None:
        return set()
    return {hc.slug for hc in discover_project_checks(root).checks}


def partition_only_slugs(
    only_raw: str,
    local_known: Iterable[str],
) -> tuple[list[str], Optional[str]]:
    """Split ``--only`` into caller-local project slugs and a relay remainder.

    Returns ``(local_slugs, relay_only)``. ``relay_only`` is ``None`` when
    every requested token is known in the caller checkout project-local
    roster — the https client then skips relayed ``only=`` validation.
    """
    known = set(local_known)
    local_run: list[str] = []
    seen_local: set[str] = set()
    relay_tokens: list[str] = []
    for raw in only_raw.split(","):
        token = raw.strip()
        if not token:
            continue
        bare = token[3:] if token.startswith("HC-") else token
        resolved = bare if bare in known else _ONLY_ALIASES.get(bare)
        if resolved is not None and resolved in known:
            if resolved not in seen_local:
                seen_local.add(resolved)
                local_run.append(resolved)
            continue
        relay_tokens.append(token)
    return local_run, (",".join(relay_tokens) if relay_tokens else None)


def prepare_https_only_payload(
    payload: Dict[str, Any],
) -> tuple[Dict[str, Any], list[str]]:
    """Rewrite https ``only=`` so undeployed project-local slugs stay local.

    Returns ``(relay_payload, local_project_slugs)``. Local slugs are removed
    from the relayed ``only`` string (or the key is dropped when none remain)
    so server-side roster validation cannot reject checkout-declared checks.
    """
    out = dict(payload)
    only_raw = out.get("only")
    project = str(out.get("project") or "")
    if not only_raw or not isinstance(only_raw, str):
        return out, []
    if checkout_root_for_project(project) is None:
        return out, []
    local_slugs, relay_only = partition_only_slugs(
        only_raw, caller_project_local_slugs(project),
    )
    if not local_slugs:
        return out, []
    if relay_only is None:
        out.pop("only", None)
    else:
        out["only"] = relay_only
    return out, local_slugs


def https_relay_needed(payload: Dict[str, Any]) -> bool:
    """True when the https payload still carries a server-side scope flag."""
    return bool(payload.get("only") or payload.get("quick") or payload.get("full"))


def run_local_project_checks(
    *,
    project: str,
    slugs: Sequence[str],
    fix: bool = False,
) -> List[Dict[str, Any]]:
    """Execute named project-local HCs against *project*'s own checkout.

    Discovery already reads the mapped checkout; binding the same root
    keeps a check that resolves the repository root — as most do — on that
    tree rather than on the caller's.
    """
    if not slugs:
        return []
    root = checkout_root_for_project(project)
    if root is None:
        return []
    wanted = set(slugs)
    args = DoctorArgs(
        only=",".join(sorted(wanted)),
        quick=False,
        project=str(project),
        fix=fix,
        runtime=RUNTIME_LOCAL,
    )
    rec = RecordCollector()
    conn = local_connection_or_none(connect)
    owned = conn is not None
    if conn is None:
        conn = UnavailableControlPlane()
    try:
        discovery = discover_project_checks(root)
        record_discovery_failures(
            Roster(discovery_failures=list(discovery.failures)), rec,
        )
        with bound_source_root(root):
            for hc in discovery.checks:
                if hc.slug not in wanted:
                    continue
                pre = len(rec.results)
                # Withheld, then emitted below: without a control plane
                # this check's failure is the runner's, and the rewrite
                # that says so happens after the call returns.
                with doctor_progress.verdicts_withheld():
                    execute_check_isolated(conn, args, rec, hc)
                    if not owned:
                        note_missing_control_plane(rec.results[pre:], project)
                for record in rec.results[pre:]:
                    doctor_progress.check_finished(
                        record.check_id, record.result
                    )
    finally:
        if owned:
            try:
                conn.close()
            except Exception:
                pass
    return [
        {
            "hc": r.check_id,
            "name": r.check_name,
            "severity": r.result,
            "detail": r.detail,
        }
        for r in rec.results
    ]


def local_project_only_result(
    *,
    project: str,
    slugs: Sequence[str],
    fix: bool = False,
    runtime: str = RUNTIME_LOCAL,
) -> Dict[str, Any]:
    """Build a ``doctor.run.run`` result for an all-local ``--only`` set."""
    rows = run_local_project_checks(project=project, slugs=slugs, fix=fix)
    counts = recount(rows)
    return {
        "results": rows,
        "scope": "only",
        "project": str(project),
        "runtime": runtime,
        **counts,
        "composed": "local_project_checks",
    }


__all__ = [
    "caller_project_local_slugs",
    "checkout_root_for_project",
    "https_relay_needed",
    "local_project_only_result",
    "partition_only_slugs",
    "prepare_https_only_payload",
    "run_local_project_checks",
]
